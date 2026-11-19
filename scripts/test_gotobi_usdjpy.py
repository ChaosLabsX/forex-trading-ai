r"""gotobi_usdjpy_v1 trades exactly the pre-registered calendar and hours.

    python scripts\test_gotobi_usdjpy.py

Its whole content is a calendar and a clock, so those are what must be right:
which Tokyo dates count, which bar fires, and when the backtest marks the
trade out. The last is checked through the real backtest code path
(run_backtest_for_symbol) on synthetic bars, not by reading an attribute. It
must not be loaded by either engine - the engine has no timed exit.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings                                                    # noqa: E402
from engine.core.interfaces.strategy import StrategyContext                           # noqa: E402
from engine.core.models import AccountState, Candle, Direction, Timeframe             # noqa: E402
from engine.plugins.strategies.gotobi_usdjpy_v1 import GotobiUSDJPYStrategy, is_gotobi  # noqa: E402
from engine.registry import load_plugin                                               # noqa: E402

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = AccountState(balance=1000, equity=1000, margin_used=0, open_positions_count=0,
                       daily_pnl=0, consecutive_stop_losses_today=0)
START = datetime(2026, 9, 1, tzinfo=UTC)
STEP = 0.001  # each synthetic H1 bar closes this much above the last


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def h1_bars(end: datetime) -> list[Candle]:
    bars, t, k = [], START, 0
    while t < end:
        o, c = 150 + STEP * (k - 1), 150 + STEP * k
        bars.append(Candle("USDJPY", Timeframe.H1, t, o, c + 0.05, o - 0.05, c, 1.0))
        t, k = t + timedelta(hours=1), k + 1
    return bars


def d1_bars(end: datetime) -> list[Candle]:
    t, bars = datetime(2026, 5, 1, tzinfo=UTC), []
    while t < end:
        bars.append(Candle("USDJPY", Timeframe.D1, t, 150.0, 150.5, 149.5, 150.0, 1.0))
        t += timedelta(days=1)
    return bars


class SyntheticHistory:
    def __init__(self, end: datetime) -> None:
        self.bars = {Timeframe.H1: h1_bars(end), Timeframe.D1: d1_bars(end)}
        self.asked: list[tuple[str, Timeframe, int]] = []

    def get_history(self, symbol, timeframe, count):
        self.asked.append((symbol, timeframe, count))
        return list(self.bars[timeframe])


def main() -> int:
    settings = Settings()
    strategy = GotobiUSDJPYStrategy(settings)
    results = []

    print("identity")
    results.append(check("built through the registry as this class",
                         type(load_plugin("strategy", "gotobi_usdjpy_v1", settings)), GotobiUSDJPYStrategy))
    results.append(check("USDJPY only", strategy.instruments, ("USDJPY",)))
    results.append(check("H1 clock, D1 stop", strategy.required_timeframes, (Timeframe.H1, Timeframe.D1)))

    print("the calendar (Tokyo dates)")
    results.append(check("Tue 10 Nov 2026: divisible by five", is_gotobi(date(2026, 11, 10)), True))
    results.append(check("Wed 11 Nov 2026: not", is_gotobi(date(2026, 11, 11)), False))
    results.append(check("Fri 13 Nov 2026: Sun 15th moves to it", is_gotobi(date(2026, 11, 13)), True))
    results.append(check("Fri 9 Oct 2026: Sat 10th moves to it", is_gotobi(date(2026, 10, 9)), True))
    results.append(check("Mon 30 Nov 2026: Mondays left out", is_gotobi(date(2026, 11, 30)), False))
    results.append(check("Fri 6 Nov 2026: no gotobi that weekend", is_gotobi(date(2026, 11, 6)), False))
    results.append(check("Sat 5 Dec 2026: not a business day", is_gotobi(date(2026, 12, 5)), False))

    print("the clock: fires on the bar that closes at 03:00 Tokyo, long, no target")
    end = datetime(2026, 12, 1, tzinfo=UTC)
    md = SyntheticHistory(end)
    h1, d1 = md.bars[Timeframe.H1], md.bars[Timeframe.D1]

    def evaluate_at(t: datetime):
        window = [c for c in h1 if c.time <= t][-300:]
        days = [c for c in d1 if c.time + timedelta(days=1) <= t + timedelta(hours=1)][-90:]
        ctx = StrategyContext(symbol="USDJPY", candles_by_timeframe={Timeframe.H1: window, Timeframe.D1: days},
                              account_state=ACCOUNT, open_positions=[], upcoming_news=())
        return strategy.evaluate(ctx).signal

    sig = evaluate_at(datetime(2026, 11, 9, 17, tzinfo=UTC))
    results.append(check("Mon 9 Nov 17:00 UTC bar (fix Tue 10th) fires", sig is not None, True))
    if sig is not None:
        results.append(check("long, stop one daily ATR below, no target",
                             (sig.direction, round(sig.entry_price - sig.stop_loss, 9), sig.take_profit),
                             (Direction.LONG, 1.0, None)))
    results.append(check("16:00 UTC bar the same day is silent",
                         evaluate_at(datetime(2026, 11, 9, 16, tzinfo=UTC)), None))
    results.append(check("Tue 10 Nov 17:00 UTC (fix Wed 11th) is silent",
                         evaluate_at(datetime(2026, 11, 10, 17, tzinfo=UTC)), None))

    print("the backtest, real code path: which days trade, and when each is marked out")
    sys.path.insert(0, str(ROOT / "scripts"))
    import backtest as bt  # noqa: E402
    outcomes = bt.run_backtest_for_symbol(strategy, md, "USDJPY", manager=None)
    results.append(check("asks for 99,999 H1 bars", md.asked[0], ("USDJPY", Timeframe.H1, 99_999)))
    want = [date(2026, 9, d) for d in (14, 17, 24, 29)] + \
           [date(2026, 10, d) for d in (8, 14, 19, 22, 29)] + \
           [date(2026, 11, d) for d in (4, 9, 12, 19, 24)]
    results.append(check("trades the evening before each gotobi, Sep 14 to Nov 30",
                         [o.entry_time.date() for o in outcomes], want))
    results.append(check("every signal is the 17:00 UTC bar",
                         {o.entry_time.hour for o in outcomes}, {17}))
    # Filled at 18:00 UTC, marked out at the close of the 00:00 bar: seven
    # bars of STEP each, over a one-unit daily ATR.
    results.append(check("each ends by time, 01:00 UTC (fix + 5 min), not by stop",
                         {(o.result, round(o.gross_r, 9)) for o in outcomes}, {("timeout", round(7 * STEP, 9))}))

    print("loaded by neither engine")
    plugins = yaml.safe_load((ROOT / "config" / "plugins.yaml").read_text(encoding="utf-8"))
    results.append(check("not in config/plugins.yaml", "gotobi_usdjpy_v1" in plugins["strategies"], False))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
