from __future__ import annotations

from datetime import timedelta

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, Signal, Timeframe
from engine.indicators import atr
from engine.plugins.strategies._common import TREND_DAILY_GROUPS, TREND_DAILY_UNIVERSE, has_open_position

CLOCK_TIMEFRAME = Timeframe.H4  # when to look; never what to look at
SIGNAL_TIMEFRAME = Timeframe.D1

# The published Turtle "System 2" numbers (1983), taken as they are and not
# fitted to anything here: break of the prior 55 days' extreme, stop 2 ATR(20)
# away. Pre-registered in docs/research-log.md (2026-11-13) before any run.
CHANNEL_DAYS = 55
ATR_PERIOD = 20
STOP_ATR_MULTIPLE = 2.0


class TrendDailyStrategy(StrategyPlugin):
    """Slow trend-following: a daily close beyond the prior 55 days' range.

    Why this is a different claim from everything tested before it. Every
    strategy in the research log died the same way: a signal worth about zero
    before costs, and a cost of ~0.08R because the stop was 10-20 pips. Here the
    stop is two DAILY ATRs - of the order of 100+ pips - so the same spread and
    commission come to about a hundredth of the risk. Cost stops being the
    story, and what is left is the question itself: do prices that break out of
    a multi-month range keep going? That is time-series momentum at the horizon
    where it is actually documented (months, across asset classes), not the
    H1 compression of it that donchian_breakout_v1 tested and that failed.

    What replaces spread as the toll is overnight financing: a position held
    for weeks pays (or earns) swap every night. scripts/backtest.py charges it.

    No target. A trend-follower's whole return is a few long runs, so the exit
    is the engine's own stop management and nothing else: to entry at +1R,
    then trailing 1R (two daily ATRs) behind price past +2R.

    H4 is in required_timeframes only as a clock. Every number comes from
    CLOSED daily bars; the H4 bar says when to act on them - once, at the close
    of the first H4 bar of the new day (04:00 broker time). Not at the daily
    close itself: that is the rollover minute, where spreads are widest and the
    risk engine refuses entries, so a strategy that fired there would never
    trade at all.
    """

    name = "trend_daily_v1"
    required_timeframes = (CLOCK_TIMEFRAME, SIGNAL_TIMEFRAME)
    instruments = TREND_DAILY_UNIVERSE
    # scripts/backtest.py: a year of H4 bars. The engine never times a trade
    # out, so the backtest must not cut this one's long runs at its H1 default.
    backtest_max_hold_bars = 1560
    report_groups = TREND_DAILY_GROUPS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if has_open_position(context):
            return StrategyEvaluation(None, "position already open for this symbol")

        h4 = context.candles_by_timeframe.get(CLOCK_TIMEFRAME, [])
        d1 = context.candles_by_timeframe.get(SIGNAL_TIMEFRAME, [])
        if len(h4) < 2 or len(d1) < CHANNEL_DAYS + ATR_PERIOD + 2:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        day = d1[-1]
        # Act on a closed day exactly once: when the first H4 bar after it has
        # closed. Every later bar of the new day sees the same daily bars and
        # must not fire again.
        next_day = day.time + timedelta(days=1)
        if not (h4[-1].time >= next_day > h4[-2].time):
            return StrategyEvaluation(None, "not the first H4 bar after a daily close")

        # The channel is the 55 days BEFORE the one that just closed - a bar
        # cannot break a range that already contains it.
        channel = d1[-(CHANNEL_DAYS + 1) : -1]
        channel_high = max(c.high for c in channel)
        channel_low = min(c.low for c in channel)

        atr_value = atr(d1, ATR_PERIOD)
        if atr_value is None or atr_value <= 0:
            return StrategyEvaluation(None, "ATR unavailable")

        if day.close > channel_high:
            direction = Direction.LONG
        elif day.close < channel_low:
            direction = Direction.SHORT
        else:
            return StrategyEvaluation(None, f"daily close inside the {CHANNEL_DAYS}-day range - no breakout")

        entry = day.close
        sign = 1.0 if direction == Direction.LONG else -1.0
        return StrategyEvaluation(
            Signal(
                strategy_name=self.name,
                symbol=context.symbol,
                direction=direction,
                timeframe=SIGNAL_TIMEFRAME,
                entry_price=entry,
                stop_loss=entry - sign * STOP_ATR_MULTIPLE * atr_value,
                take_profit=None,
                reason=(
                    f"daily close {direction.value} out of the {CHANNEL_DAYS}-day range "
                    f"({channel_low:.5f}/{channel_high:.5f})"
                ),
                metadata={
                    "channel_high": channel_high,
                    "channel_low": channel_low,
                    "atr_d1": atr_value,
                },
            ),
            f"daily close {direction.value} out of the {CHANNEL_DAYS}-day range",
        )
