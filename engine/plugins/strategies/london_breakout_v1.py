from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, Signal, Timeframe
from engine.indicators import atr
from engine.plugins.strategies._common import (
    UNIVERSE,
    has_open_position,
    news_blackout,
)

ENTRY_TIMEFRAME = Timeframe.H1
ATR_PERIOD = 14

# The Asian session: low participation, price typically rotates in a range.
ASIAN_END_HOUR_UTC = 7
MIN_ASIAN_BARS = 4
# London arrives and volatility steps up. Only hunt the break in that window -
# a break at 18:00 is not the same event, whatever the chart looks like.
TRIGGER_START_HOUR_UTC = 7
TRIGGER_END_HOUR_UTC = 11

# The premise is a COMPRESSED range releasing. If the Asian range is already
# wide relative to normal volatility, nothing was coiled and there is nothing to
# release - that's just chasing a market already in motion.
MAX_RANGE_ATR_MULTIPLE = 1.5

STOP_ATR_MULTIPLE = 1.0
TARGET_ATR_MULTIPLE = 1.5


class LondonBreakoutStrategy(StrategyPlugin):
    """Asian-range breakout at the London open.

    Structural rationale (why this isn't just a shape on a chart): the Asian
    session is thin and mean-reverting; London's open is a scheduled, repeating
    liquidity and volatility regime shift. Orders accumulated overnight get
    worked when the book deepens. That is a mechanism, not a pattern - which is
    the only kind of premise worth testing.

    Chosen partly for measurability: at most one setup per symbol per day across
    16 symbols, it can reach a statistically judgeable sample in weeks rather
    than the years ema_trend_v1 needs. Frequency is engineering; whether the
    edge survives costs is an empirical question the backtest answers, and the
    honest prior is that it does not.
    """

    name = "london_breakout_v1"
    required_timeframes = (ENTRY_TIMEFRAME,)
    instruments = UNIVERSE

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if has_open_position(context):
            return StrategyEvaluation(None, "position already open for this symbol")

        h1 = context.candles_by_timeframe.get(ENTRY_TIMEFRAME, [])
        if len(h1) < ATR_PERIOD + MIN_ASIAN_BARS + 2:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        latest = h1[-1]
        previous = h1[-2]
        as_of = latest.time

        if not (TRIGGER_START_HOUR_UTC <= as_of.hour < TRIGGER_END_HOUR_UTC):
            return StrategyEvaluation(
                None, f"outside the London-open trigger window (bar hour {as_of.hour:02d}:00 UTC)"
            )

        blackout = news_blackout(context, as_of)
        if blackout:
            return StrategyEvaluation(None, blackout)

        asian = [c for c in h1 if c.time.date() == as_of.date() and c.time.hour < ASIAN_END_HOUR_UTC]
        if len(asian) < MIN_ASIAN_BARS:
            return StrategyEvaluation(
                None, f"only {len(asian)} Asian-session bars today (need {MIN_ASIAN_BARS})"
            )

        asian_high = max(c.high for c in asian)
        asian_low = min(c.low for c in asian)
        range_size = asian_high - asian_low

        atr_value = atr(h1, ATR_PERIOD)
        if atr_value is None or atr_value <= 0:
            return StrategyEvaluation(None, "ATR unavailable")

        if range_size > MAX_RANGE_ATR_MULTIPLE * atr_value:
            return StrategyEvaluation(
                None,
                f"Asian range {range_size:.5f} is not compressed "
                f"(> {MAX_RANGE_ATR_MULTIPLE}x ATR {atr_value:.5f}) - nothing coiled to release",
            )

        # The break must be FRESH: the prior bar closed inside the range. Without
        # this the strategy re-fires on every bar that merely remains outside,
        # which would flatter the trade count with duplicates of one idea.
        prev_inside = asian_low <= previous.close <= asian_high
        if not prev_inside:
            return StrategyEvaluation(None, "range was already broken on an earlier bar")

        if latest.close > asian_high:
            direction = Direction.LONG
        elif latest.close < asian_low:
            direction = Direction.SHORT
        else:
            return StrategyEvaluation(
                None, "price still inside the Asian range - no break at the London open"
            )

        entry = latest.close
        sign = 1.0 if direction == Direction.LONG else -1.0
        return StrategyEvaluation(
            Signal(
                strategy_name=self.name,
                symbol=context.symbol,
                direction=direction,
                timeframe=ENTRY_TIMEFRAME,
                entry_price=entry,
                stop_loss=entry - sign * STOP_ATR_MULTIPLE * atr_value,
                take_profit=entry + sign * TARGET_ATR_MULTIPLE * atr_value,
                reason=(
                    f"London-open break {direction.value} of a compressed Asian range "
                    f"({range_size:.5f} <= {MAX_RANGE_ATR_MULTIPLE}x ATR)"
                ),
                metadata={
                    "asian_high": asian_high,
                    "asian_low": asian_low,
                    "range_size": range_size,
                    "atr": atr_value,
                },
            ),
            f"London-open break {direction.value} of a compressed Asian range",
        )
