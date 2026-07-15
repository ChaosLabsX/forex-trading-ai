from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, Signal, Timeframe
from engine.indicators import adx, atr, ema
from engine.plugins.strategies._common import UNIVERSE, has_open_position, news_blackout

ENTRY_TIMEFRAME = Timeframe.H1
REGIME_TIMEFRAME = Timeframe.H4

MEAN_EMA = 20
ATR_PERIOD = 14
ADX_PERIOD = 14

# The regime gate, inverted relative to ema_trend_v1: that strategy demands
# ADX >= 20 (a trend). This one demands ADX < 20 - it only fades when there is
# demonstrably no trend to be run over by.
ADX_RANGE_CEILING = 20

# How far beyond the mean counts as overextended, in ATRs.
BAND_ATR_MULTIPLE = 1.5
STOP_ATR_MULTIPLE = 1.0
TARGET_ATR_MULTIPLE = 1.5

# Wider than ema_trend_v1's 12-16 window: mean reversion doesn't depend on the
# London/NY liquidity surge, and the extra hours are extra samples. Still avoids
# the thinnest hours, where spreads widen enough to eat the whole premise.
SESSION_START_UTC_HOUR = 7
SESSION_END_UTC_HOUR = 20


class RangeFadeStrategy(StrategyPlugin):
    """Fade over-extension back toward the mean, in range-bound regimes only.

    Structural rationale: without a directional driver, price in a liquid FX
    pair rotates around a local mean as market makers lean against flow. The
    premise is inventory/liquidity provision, not chart geometry.

    Deliberately the COMPLEMENT of ema_trend_v1: it requires ADX < 20 where that
    one requires ADX >= 20, so the two cannot both be right about the same bar,
    and between them they cover both regimes. If trend-following has no edge
    because markets are mostly ranging, this is where that edge would live -
    which is exactly why it is worth one honest test.

    The killer for this family is costs: fades win often and win small, so the
    spread + commission per trade is a large share of the take. Expect the
    backtest to show a good win rate and a mediocre expectancy. That is the
    trap this whole harness exists to expose.
    """

    name = "range_fade_v1"
    # Timeframes are CLASS attributes, not module constants, so the same
    # evaluate() can run at another scale without being copied. That matters:
    # cost-in-R is commission / (stop x value), so it shrinks as the stop grows -
    # the identical signal on a bigger bar carries a smaller cost drag. A
    # subclass changing only these is a scale test, not a new strategy.
    entry_tf = ENTRY_TIMEFRAME
    regime_tf = REGIME_TIMEFRAME
    required_timeframes = (ENTRY_TIMEFRAME, REGIME_TIMEFRAME)
    instruments = UNIVERSE

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if has_open_position(context):
            return StrategyEvaluation(None, "position already open for this symbol")

        h1 = context.candles_by_timeframe.get(self.entry_tf, [])
        h4 = context.candles_by_timeframe.get(self.regime_tf, [])
        if len(h1) < MEAN_EMA + ATR_PERIOD + 2 or len(h4) < ADX_PERIOD * 3:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        latest = h1[-1]
        previous = h1[-2]
        as_of = latest.time

        if not (SESSION_START_UTC_HOUR <= as_of.hour < SESSION_END_UTC_HOUR):
            return StrategyEvaluation(
                None, f"outside the traded session (bar hour {as_of.hour:02d}:00 UTC)"
            )

        blackout = news_blackout(context, as_of)
        if blackout:
            return StrategyEvaluation(None, blackout)

        adx_h4 = adx(h4, ADX_PERIOD)
        if adx_h4 is None:
            return StrategyEvaluation(None, "insufficient H4 history for the regime filter")
        if adx_h4 >= ADX_RANGE_CEILING:
            return StrategyEvaluation(
                None,
                f"ADX({adx_h4:.1f}) >= {ADX_RANGE_CEILING} - trending, and fading a trend is how "
                f"mean reversion dies",
            )

        closes = [c.close for c in h1]
        mean = ema(closes, MEAN_EMA)
        atr_value = atr(h1, ATR_PERIOD)
        if mean is None or atr_value is None or atr_value <= 0:
            return StrategyEvaluation(None, "indicators unavailable")

        band = BAND_ATR_MULTIPLE * atr_value
        upper, lower = mean + band, mean - band

        # Fresh extension only: without this it re-fires every bar price stays
        # outside the band, inflating the trade count with one idea counted many
        # times - which would corrupt the very statistics we judge it by.
        if not (lower <= previous.close <= upper):
            return StrategyEvaluation(None, "already extended on the previous bar")

        if latest.close < lower:
            direction = Direction.LONG
        elif latest.close > upper:
            direction = Direction.SHORT
        else:
            return StrategyEvaluation(
                None, f"within {BAND_ATR_MULTIPLE} ATR of the mean - not over-extended"
            )

        entry = latest.close
        sign = 1.0 if direction == Direction.LONG else -1.0
        return StrategyEvaluation(
            Signal(
                strategy_name=self.name,
                symbol=context.symbol,
                direction=direction,
                timeframe=self.entry_tf,
                entry_price=entry,
                stop_loss=entry - sign * STOP_ATR_MULTIPLE * atr_value,
                take_profit=entry + sign * TARGET_ATR_MULTIPLE * atr_value,
                reason=(
                    f"fade {direction.value}: close {BAND_ATR_MULTIPLE}+ ATR beyond EMA({MEAN_EMA}) "
                    f"in a range regime (ADX {adx_h4:.1f})"
                ),
                metadata={"mean": mean, "adx_h4": adx_h4, "atr": atr_value},
            ),
            f"fade {direction.value} toward the mean in a range regime (ADX {adx_h4:.1f})",
        )
