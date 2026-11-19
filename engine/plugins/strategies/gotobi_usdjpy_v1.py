from __future__ import annotations

from datetime import date, timedelta

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, Signal, Timeframe
from engine.indicators import atr
from engine.plugins.strategies._common import has_open_position, news_blackout

ENTRY_TIMEFRAME = Timeframe.H1
STOP_TIMEFRAME = Timeframe.D1

# Japan keeps no daylight saving: Tokyo is UTC+9 all year, so these are fixed.
# The H1 bar that opens 17:00 UTC closes 18:00 UTC = 03:00 Tokyo - where the
# pre-fix dollar buying begins (Bessho, Sugimoto & Suzuki 2023). The fill is at
# that close; the fix is 09:55 Tokyo = 00:55 UTC.
CLOCK_BAR_HOUR_UTC = 17
TOKYO_OFFSET = timedelta(hours=9)
# Six H1 bars after the fill bar: the last is 00:00-01:00 UTC, so the trade is
# marked out at 10:00 Tokyo - the fix, plus five minutes. Hourly bars cannot
# end at 09:55; Ito & Yamada's hourly work made the same approximation.
HOLD_BARS = 6

ATR_PERIOD = 14
STOP_ATR_MULTIPLE = 1.0  # one day's range: a disaster stop, rarely reached in 7 hours


def is_gotobi(day: date) -> bool:
    """A Tokyo business date on which "gotobi" payments settle: a date
    divisible by five, or the Friday before one that falls on a weekend
    (payments move to the previous business day). Mondays are left out, as in
    Bessho et al.: Tokyo's Monday morning market is thin. Japanese public
    holidays are not modelled - on those the trade fires anyway."""
    weekday = day.weekday()
    if weekday == 0 or weekday >= 5:
        return False
    if day.day % 5 == 0:
        return True
    if weekday == 4:
        return any((day + timedelta(days=k)).day % 5 == 0 for k in (1, 2))
    return False


class GotobiUSDJPYStrategy(StrategyPlugin):
    """Long USD/JPY into the Tokyo fix on gotobi days.

    Structural rationale: Japanese importers settle on dates divisible by five
    and buy their dollars at the 09:55 Tokyo fix. Their orders reach the banks
    before it, so dollar demand is predictable by the calendar alone. Ito &
    Yamada (J. Int. Econ. 2017) document pre-fix order flow skewed toward
    buying dollars and a fix biased toward dollar strength; Bessho, Sugimoto &
    Suzuki (arXiv 2023, 2018-2020 one-minute data) find USD/JPY rising from
    about 03:00 Tokyo to the fix on gotobi days and not on others. The
    information is the calendar, not a price pattern.

    Nothing here is fitted: the hours are the paper's, the stop is one daily
    ATR, there is no target and no filter. Pre-registered in
    docs/research-log.md (2026-11-19) before any run.

    NOT RUNNABLE IN THE ENGINE YET. The exit is a time, and the engine has no
    timed exit - it would hold this trade until its stop. The backtest marks
    it out after HOLD_BARS (`backtest_max_hold_bars`). A pass means building
    that exit, and testing it, before any demo run. Registered for backtests
    only; not in config/plugins.yaml.
    """

    name = "gotobi_usdjpy_v1"
    required_timeframes = (ENTRY_TIMEFRAME, STOP_TIMEFRAME)
    instruments = ("USDJPY",)
    backtest_history_bars = 99_999
    backtest_max_hold_bars = HOLD_BARS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if has_open_position(context):
            return StrategyEvaluation(None, "position already open for this symbol")

        h1 = context.candles_by_timeframe.get(ENTRY_TIMEFRAME, [])
        d1 = context.candles_by_timeframe.get(STOP_TIMEFRAME, [])
        if not h1 or len(d1) < ATR_PERIOD + 1:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        latest = h1[-1]
        as_of = latest.time
        if as_of.hour != CLOCK_BAR_HOUR_UTC:
            return StrategyEvaluation(None, f"not the 03:00 Tokyo bar (bar hour {as_of.hour:02d}:00 UTC)")

        fix_day = (as_of + timedelta(hours=1) + TOKYO_OFFSET).date()
        if not is_gotobi(fix_day):
            return StrategyEvaluation(None, f"{fix_day:%a %d %b} is not a gotobi day in Tokyo")

        blackout = news_blackout(context, as_of)
        if blackout:
            return StrategyEvaluation(None, blackout)

        atr_value = atr(d1, ATR_PERIOD)
        if atr_value is None or atr_value <= 0:
            return StrategyEvaluation(None, "ATR unavailable")

        entry = latest.close
        return StrategyEvaluation(
            Signal(
                strategy_name=self.name,
                symbol=context.symbol,
                direction=Direction.LONG,
                timeframe=ENTRY_TIMEFRAME,
                entry_price=entry,
                stop_loss=entry - STOP_ATR_MULTIPLE * atr_value,
                take_profit=None,
                reason=f"gotobi {fix_day:%a %d %b}: long USD/JPY into the 09:55 Tokyo fix",
                metadata={"fix_day": fix_day.isoformat(), "atr_d1": atr_value},
            ),
            f"gotobi {fix_day:%d %b}: long into the Tokyo fix",
        )
