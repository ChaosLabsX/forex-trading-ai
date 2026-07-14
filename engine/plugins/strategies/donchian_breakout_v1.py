from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, Signal, Timeframe
from engine.indicators import atr
from engine.plugins.strategies._common import UNIVERSE, has_open_position, news_blackout

ENTRY_TIMEFRAME = Timeframe.H1

CHANNEL_BARS = 20  # break of the prior 20 H1 bars' extreme
ATR_PERIOD = 14

# Asymmetric by design: momentum pays through a few large winners, so the target
# must be well beyond the stop. A 1:1 breakout system loses to costs even with a
# >50% win rate.
STOP_ATR_MULTIPLE = 1.5
TARGET_ATR_MULTIPLE = 3.0

SESSION_START_UTC_HOUR = 7
SESSION_END_UTC_HOUR = 20


class DonchianBreakoutStrategy(StrategyPlugin):
    """Break of an N-bar price channel, with an ATR stop and a runner target.

    Structural rationale: time-series momentum is one of the few effects with
    genuine, decades-long academic support across asset classes (Moskowitz/Ooi/
    Pedersen and the Donchian/turtle lineage). The mechanism usually offered is
    under-reaction to information plus flow begetting flow. That is a real prior
    - unlike most chart patterns, which are just shapes.

    Different MECHANISM from ema_trend_v1 even though both are trend-ish: this
    triggers on price itself taking out a level (an event traders act on),
    rather than a lagging average crossing another lagging average. Testing both
    is testing two claims, not the same claim twice.

    The honest caveat: this effect is best documented on MONTHLY horizons in
    diversified futures portfolios, not H1 bars on FX majors after retail
    spreads. Compressing a slow effect into a fast timeframe is exactly where
    edges evaporate into costs. Worth one test; not worth optimism.
    """

    name = "donchian_breakout_v1"
    required_timeframes = (ENTRY_TIMEFRAME,)
    instruments = UNIVERSE

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if has_open_position(context):
            return StrategyEvaluation(None, "position already open for this symbol")

        h1 = context.candles_by_timeframe.get(ENTRY_TIMEFRAME, [])
        if len(h1) < CHANNEL_BARS + ATR_PERIOD + 2:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        latest = h1[-1]
        as_of = latest.time

        if not (SESSION_START_UTC_HOUR <= as_of.hour < SESSION_END_UTC_HOUR):
            return StrategyEvaluation(
                None, f"outside the traded session (bar hour {as_of.hour:02d}:00 UTC)"
            )

        blackout = news_blackout(context, as_of)
        if blackout:
            return StrategyEvaluation(None, blackout)

        # The channel is built from bars BEFORE the latest one. Including the
        # breaking bar's own high in its own channel would make a break
        # impossible by construction - a subtle lookahead that silently produces
        # zero signals.
        channel = h1[-(CHANNEL_BARS + 1) : -1]
        channel_high = max(c.high for c in channel)
        channel_low = min(c.low for c in channel)

        atr_value = atr(h1, ATR_PERIOD)
        if atr_value is None or atr_value <= 0:
            return StrategyEvaluation(None, "ATR unavailable")

        if latest.close > channel_high:
            direction = Direction.LONG
        elif latest.close < channel_low:
            direction = Direction.SHORT
        else:
            return StrategyEvaluation(
                None, f"inside the {CHANNEL_BARS}-bar channel - no breakout"
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
                    f"{direction.value} break of the {CHANNEL_BARS}-bar channel "
                    f"({channel_high:.5f}/{channel_low:.5f})"
                ),
                metadata={
                    "channel_high": channel_high,
                    "channel_low": channel_low,
                    "atr": atr_value,
                },
            ),
            f"{direction.value} break of the {CHANNEL_BARS}-bar channel",
        )
