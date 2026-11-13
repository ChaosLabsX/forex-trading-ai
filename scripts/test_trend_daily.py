r"""trend_daily_v1 does what its pre-registration says, and the backtest that
judges it cannot see the future, hold two positions, or invent a commission.

    .venv\Scripts\python.exe scripts\test_trend_daily.py

Two halves. The strategy: a daily close out of the prior 55 days' range, acted
on once, at the first H4 bar of the new day, with a two-daily-ATR stop and no
target (docs/research-log.md, 2026-11-13). And three faults found in
scripts/backtest.py while preparing its test, each of which would have made the
result meaningless:

1. the slower timeframe's slice included the bar still forming (a look-ahead);
2. the strategy was always shown an empty book, so repeats of one signal were
   counted as separate trades the engine would never have placed;
3. $7 a lot of commission was charged on markets that carry none.

Plus what a strategy that holds for weeks needs and an hourly one never did:
overnight financing, no target, and a hold limit that does not cut it short.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backtest                                                                    # noqa: E402
from backtest import (                                                             # noqa: E402
    StopManager, SymbolCosts, closed_context, commission_for, cost_in_r, first_intraday_index, nights_held,
    run_backtest_for_symbol, simulate_outcome, simulate_trade, swap_in_r, swap_terms,
)
from engine.config import Settings                                                 # noqa: E402
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation   # noqa: E402
from engine.core.models import (                                                   # noqa: E402
    AccountState, Candle, Direction, Position, PositionStatus, Signal, Timeframe,
)
from engine.indicators import atr                                                  # noqa: E402
from engine.plugins.strategies._common import (                                    # noqa: E402
    TREND_DAILY_GROUPS, TREND_DAILY_UNIVERSE, UNIVERSE, has_open_position,
)
from engine.registry import load_plugin                                            # noqa: E402

UTC = timezone.utc
H1, H4, D1 = Timeframe.H1, Timeframe.H4, Timeframe.D1
LONG, SHORT = Direction.LONG, Direction.SHORT
ACCOUNT = AccountState(10_000.0, 10_000.0, 0.0, 0, 0.0, 0)
# Broker midnight is 22:00 UTC in winter. Monday 2026-01-12's daily bar opens then.
MONDAY = datetime(2026, 1, 11, 22, tzinfo=UTC)


def check(label: str, got, want) -> bool:
    ok = (abs(got - want) < 1e-9) if isinstance(want, float) and isinstance(got, (int, float)) else got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def daily_bars(last_close: float, last_day: datetime = MONDAY + timedelta(days=3), n: int = 89) -> list[Candle]:
    """n closed daily bars oscillating in 100..102 (every high <= 102, low >= 100),
    the last one - `last_day` - closing at `last_close`. Weekends skipped."""
    days, day = [], last_day
    while len(days) < n:
        if day.weekday() not in (4, 5):  # bars that open Fri/Sat 22:00 UTC are the weekend
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    bars = [Candle("EURUSD", D1, t, 101.0, 102.0, 100.0, 101.0, 1.0) for t in days]
    high, low = max(102.0, last_close), min(100.0, last_close)
    bars[-1] = Candle("EURUSD", D1, days[-1], 101.0, high, low, last_close, 1.0)
    return bars


def h4_bars(last_open: datetime, n: int = 6) -> list[Candle]:
    return [Candle("EURUSD", H4, last_open - timedelta(hours=4 * k), 101, 101, 101, 101, 1.0)
            for k in reversed(range(n))]


def evaluate(strategy, d1, h4, positions=()):
    return strategy.evaluate(StrategyContext("EURUSD", {H4: h4, D1: d1}, ACCOUNT, list(positions), ()))


def flat(tf: Timeframe, start: datetime, n: int, price: float = 100.0) -> list[Candle]:
    step = timedelta(hours=backtest.TF_HOURS[tf])
    return [Candle("EURUSD", tf, start + k * step, price, price + 0.5, price - 0.5, price, 1.0) for k in range(n)]


def main() -> int:
    passed = []
    settings = Settings(_env_file=None)
    strategy = load_plugin("strategy", "trend_daily_v1", settings)

    print("the strategy: a daily close out of the 55-day range, acted on once")
    thursday = MONDAY + timedelta(days=3)          # the daily bar that just closed
    first_h4 = thursday + timedelta(days=1)        # Friday's first H4 bar: opens as Thursday closes
    up = daily_bars(103.0)
    ev = evaluate(strategy, up, h4_bars(first_h4))
    expected_atr = atr(up, 20)
    passed.append(check("close above the prior 55 days' high, first H4 bar of the new day: LONG",
                        ev.signal and ev.signal.direction, LONG))
    passed.append(check("entry is that daily close", ev.signal.entry_price, 103.0))
    passed.append(check("stop is 2 x ATR(20, daily) below it", ev.signal.stop_loss, 103.0 - 2 * expected_atr))
    passed.append(check("no target", ev.signal.take_profit, None))
    ev = evaluate(strategy, up, h4_bars(first_h4 + timedelta(hours=4)))
    passed.append(check("the same daily bars one H4 bar later: nothing (fires once a day)",
                        (ev.signal, ev.reason), (None, "not the first H4 bar after a daily close")))
    ev = evaluate(strategy, up, h4_bars(first_h4 - timedelta(hours=4)))
    passed.append(check("...and not before that day has closed", ev.signal, None))
    ev = evaluate(strategy, daily_bars(97.5), h4_bars(first_h4))
    passed.append(check("close below the prior 55 days' low: SHORT, stop above",
                        (ev.signal.direction, ev.signal.stop_loss > 97.5, ev.signal.take_profit), (SHORT, True, None)))
    ev = evaluate(strategy, daily_bars(101.9), h4_bars(first_h4))
    passed.append(check("close inside the range: nothing", ev.signal, None))
    spike = daily_bars(101.9)
    spike[-1] = Candle("EURUSD", D1, spike[-1].time, 101.0, 104.0, 100.0, 101.9, 1.0)
    passed.append(check("a high above the range that CLOSES back inside: nothing (the close decides)",
                        evaluate(strategy, spike, h4_bars(first_h4)).signal, None))
    held = Position("1", "EURUSD", LONG, 0.01, 103.0, 99.0, None, PositionStatus.OPEN, first_h4)
    ev = evaluate(strategy, up, h4_bars(first_h4), [held])
    passed.append(check("already holding the symbol: declines", ev.reason, "position already open for this symbol"))
    ev = evaluate(strategy, up[-40:], h4_bars(first_h4))
    passed.append(check("too little daily history: says so, no signal",
                        (ev.signal, ev.reason), (None, "insufficient candle history for indicators")))
    friday = MONDAY + timedelta(days=4)
    monday_first = MONDAY + timedelta(days=7)
    h4 = h4_bars(friday + timedelta(hours=20)) + [Candle("EURUSD", H4, monday_first, 101, 101, 101, 101, 1.0)]
    ev = evaluate(strategy, daily_bars(103.0, last_day=friday), h4)
    passed.append(check("Friday's breakout is acted on at Monday's first H4 bar", ev.signal and ev.signal.direction, LONG))
    passed.append(check("28 markets, none twice, every one in exactly one report group",
                        (len(TREND_DAILY_UNIVERSE), len(set(TREND_DAILY_UNIVERSE)),
                         sorted(s for g in TREND_DAILY_GROUPS.values() for s in g) == sorted(TREND_DAILY_UNIVERSE)),
                        (28, 28, True)))
    passed.append(check("the lab's standing 16 are all in it", set(UNIVERSE) <= set(TREND_DAILY_UNIVERSE), True))

    print("\nthe backtest shows a strategy only bars that had closed (no look-ahead)")
    day0 = datetime(2026, 1, 12, 0, tzinfo=UTC)
    h4s = flat(H4, day0, 12)
    times = [c.time for c in h4s]
    last = lambda as_of, e, t, bars, ts: closed_context(bars, ts, as_of, e, t, 250)[-1].time  # noqa: E731
    passed.append(check("H1 bar 09:00 (judged at 10:00): the 08:00 H4 bar is still forming - last is 04:00",
                        last(day0 + timedelta(hours=9), H1, H4, h4s, times), day0 + timedelta(hours=4)))
    passed.append(check("H1 bar 11:00 (judged at 12:00): the 08:00 H4 bar has just closed - included",
                        last(day0 + timedelta(hours=11), H1, H4, h4s, times), day0 + timedelta(hours=8)))
    d1s = flat(D1, day0 - timedelta(days=5), 8)
    dtimes = [c.time for c in d1s]
    passed.append(check("H4 bar 00:00 (judged at 04:00): today's daily bar is forming - last is yesterday",
                        last(day0, H4, D1, d1s, dtimes), day0 - timedelta(days=1)))
    passed.append(check("H4 bar 20:00 (judged at 24:00): today's daily bar has just closed - included",
                        last(day0 + timedelta(hours=20), H4, D1, d1s, dtimes), day0))

    seen = []

    class TwoTimeframes:
        name, instruments, required_timeframes = "probe", ("EURUSD",), (H1, H4)

        def evaluate(self, ctx):
            seen.append((ctx.candles_by_timeframe[H1][-1].time, ctx.candles_by_timeframe[H4][-1].time))
            return StrategyEvaluation(None, "watching")

    start = datetime(2025, 1, 6, 0, tzinfo=UTC)
    history = {H1: flat(H1, start, 1400), H4: flat(H4, start, 351)}
    md = types.SimpleNamespace(get_history=lambda symbol, tf, count: history[tf])
    real_costs = backtest.resolve_costs
    backtest.resolve_costs = lambda symbol: SymbolCosts(0.0, 100_000.0, 0.0, 0.00001, True)
    try:
        run_backtest_for_symbol(TwoTimeframes(), md, "EURUSD", StopManager(settings))
        gaps = {(h1 + timedelta(hours=1)) - (h4 + timedelta(hours=4)) for h1, h4 in seen}
        passed.append(check("through the real run: every H4 bar handed over had closed, the newest one always there",
                            (len(seen) > 300, min(gaps), max(gaps)),
                            (True, timedelta(0), timedelta(hours=3))))

        print("\none position per symbol, as the engine trades it")
        calls = []

        class FiresAlways:
            name, instruments, required_timeframes = "eager", ("EURUSD",), (H1,)
            backtest_max_hold_bars = 5  # the flat market never reaches stop or target

            def evaluate(self, ctx):
                calls.append(has_open_position(ctx))
                if has_open_position(ctx):
                    return StrategyEvaluation(None, "position already open for this symbol")
                price = ctx.candles_by_timeframe[H1][-1].close
                return StrategyEvaluation(Signal("eager", "EURUSD", LONG, H1, price, price - 10, price + 10, "go"), "go")

        trades = run_backtest_for_symbol(FiresAlways(), md, "EURUSD", StopManager(settings))
        spacing = {b.entry_time - a.entry_time for a, b in zip(trades, trades[1:])}
        passed.append(check("a strategy that fires on every bar: one trade per 6 bars (5 held), not one every 2",
                            spacing, {timedelta(hours=6)}))
        passed.append(check("...because it is shown its own open trade on the bars in between",
                            (sum(calls) > 0, sum(calls) / len(calls) > 0.8), (True, True)))
        passed.append(check("...and each trade is the 5-bar timeout the strategy asked for",
                            {t.result for t in trades}, {"timeout"}))
    finally:
        backtest.resolve_costs = real_costs

    print("\nno target, a long hold, and how long it lasted")
    t0 = datetime(2026, 1, 12, 4, tzinfo=UTC)
    run = [Candle("X", H4, t0 + timedelta(hours=4 * k), 100 + k, 101 + k, 99.5 + k, 101 + k, 1.0) for k in range(12)]
    run += [Candle("X", H4, t0 + timedelta(hours=48), 112, 112, 100, 101, 1.0)]  # the trend breaks
    sim = simulate_trade(LONG, 100.0, 98.0, None, run, StopManager(settings))
    passed.append(check("a rising market with no target: never a 'win', it ends at the trailed stop",
                        (sim.result, sim.gross_r > 3.0, sim.bars_held), ("moved_stop", True, 13)))
    passed.append(check("with the same path and a target, simulate_outcome still pays the target (unchanged)",
                        simulate_outcome(LONG, 100.0, 98.0, 103.0, run, StopManager(settings)), ("win", 1.5)))
    sim = simulate_trade(LONG, 100.0, 98.0, None, flat(H4, t0, 30), None, max_hold_bars=20)
    passed.append(check("a market that goes nowhere: marked to market at the strategy's own hold limit",
                        (sim.result, sim.bars_held, sim.gross_r), ("timeout", 20, 0.0)))
    sim = simulate_trade(LONG, 100.0, 98.0, None, [Candle("X", H4, t0, 100, 100.2, 97.9, 99, 1.0)], None)
    passed.append(check("stopped on the first bar: -1R after 1 bar", (sim.result, sim.gross_r, sim.bars_held), ("loss", -1.0, 1)))

    print("\novernight financing")
    fri, mon = datetime(2026, 1, 16, 8, tzinfo=UTC), datetime(2026, 1, 19, 8, tzinfo=UTC)
    passed.append(check("Friday morning to Monday morning: 3 nights (the weekend is charged)", nights_held(fri, mon), 3))
    passed.append(check("in and out the same broker day: none", nights_held(fri, fri + timedelta(hours=6)), 0))
    passed.append(check("21:00 to 23:00 UTC in winter crosses the broker's midnight (22:00): 1",
                        nights_held(datetime(2026, 1, 14, 21, tzinfo=UTC), datetime(2026, 1, 14, 23, tzinfo=UTC)), 1))
    fx = SymbolCosts(0.0, 100_000.0, 0.0, 0.00001, True, *swap_terms(1, -7.986, 1.314, 0.00001, 100_000.0)[:4])
    passed.append(check("EURUSD long, 140-pip stop, 20 nights at -7.986 points: -0.114R",
                        round(swap_in_r(fx, LONG, 1.10, 0.0140, 20), 4), -0.1141))
    passed.append(check("...the short side earns: +0.019R", round(swap_in_r(fx, SHORT, 1.10, 0.0140, 20), 4), 0.0188))
    index = swap_terms(3, -6.043, -2.068, 0.01, 1.1054, contract_size=1.0, quoted_in_profit_currency=True)
    passed.append(check("an index quoted in its own currency per lot: that money is index points",
                        index, (-6.043, -2.068, 0.0, 0.0, True)))
    btc = SymbolCosts(0.0, 1.0, 0.0, 0.01, True, *swap_terms(5, -20.0, 0.0, 0.01, 1.0)[:4])
    passed.append(check("bitcoin long at -20% a year, 30 nights, $70,000, $3,500 stop: -0.333R",
                        round(swap_in_r(btc, LONG, 70_000.0, 3_500.0, 30), 4), -0.3333))
    passed.append(check("a quote this model cannot price: flagged, charged nothing - never guessed",
                        swap_terms(7, -5.0, -5.0, 0.01, 1.0), (0.0, 0.0, 0.0, 0.0, False)))
    passed.append(check("...including money in a currency that is not the price's own",
                        swap_terms(3, -5.0, -5.0, 0.01, 1.0, contract_size=1.0)[4], False))

    print("\na symbol is tested only where its intraday history is real")

    def year_of(year: int, bars_a_day: int, first_month: int = 1) -> list[Candle]:
        day, out = datetime(year, first_month, 1, tzinfo=UTC), []
        while day.year == year:
            out += [Candle("X", H4, day + timedelta(hours=4 * k), 1, 1, 1, 1, 1.0) for k in range(bars_a_day)]
            day += timedelta(days=1)
        return out

    gold_like = year_of(2014, 1) + year_of(2015, 1) + year_of(2016, 6) + year_of(2017, 6)
    passed.append(check("two years of one bar a day, then real H4 bars: starts at the first real year",
                        gold_like[first_intraday_index(gold_like)].time, datetime(2016, 1, 1, tzinfo=UTC)))
    capped = year_of(2023, 6, first_month=8) + year_of(2024, 6) + year_of(2025, 6)
    passed.append(check("a first year that is only partial (the bar cap landed in August) is dense: all of it stays",
                        first_intraday_index(capped), 0))
    patchy = year_of(2019, 6) + year_of(2020, 1) + year_of(2021, 6) + year_of(2022, 6)
    passed.append(check("a daily-only year in the middle: starts after it, not before",
                        patchy[first_intraday_index(patchy)].time, datetime(2021, 1, 1, tzinfo=UTC)))
    passed.append(check("a single year of data: nothing to compare, nothing dropped", first_intraday_index(year_of(2025, 6)), 0))
    stub = year_of(2024, 6)[-9:] + year_of(2025, 6) + year_of(2026, 6)
    passed.append(check("a two-day stub of a year cannot set the standard for the full ones", first_intraday_index(stub), 0))

    print("\ncommission only where the broker charges it")
    passed.append(check("FX and metals: $7 a lot",
                        (commission_for("Forex\\Majors\\EURUSD"), commission_for("Commodities\\Metals\\XAUUSD")), (7.0, 7.0)))
    passed.append(check("indices, energies, crypto: none",
                        (commission_for("Indices\\Indices Spot\\Major Spot Indices\\JP225"),
                         commission_for("Commodities\\Energies\\Energies Spot\\XTIUSD"), commission_for("Crypto\\BTCUSD")),
                        (0.0, 0.0, 0.0)))
    jp225 = SymbolCosts(4.0, 0.0063, 0.0, 0.01, True)
    passed.append(check("JP225, 2,500-point stop: at $7 a lot the model charged 0.45R on a trade that pays no commission",
                        round(cost_in_r(jp225, 2500.0), 2), 0.45))
    jp225.commission_per_lot = commission_for("Indices\\Indices Spot\\Major Spot Indices\\JP225")
    passed.append(check("...now the spread alone: 0.0016R", round(cost_in_r(jp225, 2500.0), 4), 0.0016))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
