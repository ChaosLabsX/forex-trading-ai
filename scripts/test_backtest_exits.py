r"""The backtest manages a stop the way the engine does, and the fixed model is unchanged.

    .venv\Scripts\python.exe scripts\test_backtest_exits.py

Until 2026-10-12 scripts/backtest.py held every stop where the strategy put it,
while the engine moves it to entry at +1R. So 12.7 years of backtest described a
strategy that wasn't the one trading. These checks walk hand-built H1 bars through
simulate_outcome() both ways: with the engine's own DefaultExecutionEngine moving
the stop, and with the stop held fixed exactly as before.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest import StopManager, TradeOutcome, simulate_outcome                  # noqa: E402
from engine.config import Settings                                                 # noqa: E402
from engine.core.models import Candle, Direction, Timeframe                       # noqa: E402
from engine.plugins.execution.default_execution_engine import DefaultExecutionEngine  # noqa: E402

T0 = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
LONG, SHORT = Direction.LONG, Direction.SHORT
# entry 1.0000, risk 0.0010 (10 pips): stop 0.9990, target +1.5R = 1.0015
ENTRY, STOP, TARGET = 1.0000, 0.9990, 1.0015


def check(label: str, got, want) -> bool:
    if isinstance(want, tuple) and len(want) == 2 and isinstance(want[1], float):
        ok = got[0] == want[0] and abs(got[1] - want[1]) < 1e-9
    else:
        ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def bars(*ohlc):
    return [Candle("EURUSD", Timeframe.H1, T0 + timedelta(hours=i), o, h, low, c, 1.0)
            for i, (o, h, low, c) in enumerate(ohlc)]


def both(direction, entry, stop, target, path, settings=None):
    manager = StopManager(settings or Settings(_env_file=None))
    return (simulate_outcome(direction, entry, stop, target, path, manager),
            simulate_outcome(direction, entry, stop, target, path))


def main() -> int:
    passed = []
    defaults = Settings(_env_file=None)
    print(f"(engine settings: breakeven at +{defaults.breakeven_at_r}R, trail past +{defaults.trail_start_r}R "
          f"by {defaults.trail_distance_r}R, enabled={defaults.trail_enabled})\n")

    print("the fixed model is exactly the old one")
    _, fixed = both(LONG, ENTRY, STOP, TARGET, bars((1.0, 1.0016, 0.9995, 1.0012)))
    passed.append(check("straight to target: +1.5R", fixed, ("win", 1.5)))
    _, fixed = both(LONG, ENTRY, STOP, TARGET, bars((1.0, 1.0005, 0.9989, 0.9992)))
    passed.append(check("straight to stop: -1R", fixed, ("loss", -1.0)))
    _, fixed = both(LONG, ENTRY, STOP, TARGET, bars((1.0, 1.0016, 0.9989, 1.0)))
    passed.append(check("one bar touching both: the stop (conservative)", fixed, ("loss", -1.0)))

    print("\ntoday's CHFJPY shape: +1R, then back to entry")
    path = bars((1.0, 1.0011, 0.9995, 1.0008),   # reaches +1.1R, closes +0.8R
                (1.0008, 1.0009, 0.9999, 1.0003),  # dips through entry
                (1.0003, 1.0016, 1.0001, 1.0014))  # then would have hit the target
    managed, fixed = both(LONG, ENTRY, STOP, TARGET, path)
    passed.append(check("managed: stop moved to entry, out at 0R", managed, ("moved_stop", 0.0)))
    passed.append(check("fixed: rides on to the target", fixed, ("win", 1.5)))

    print("\na bar that reaches +1R and closes below entry")
    path = bars((1.0, 1.0011, 0.9995, 0.9997), (0.9997, 0.9998, 0.9989, 0.9990))
    managed, fixed = both(LONG, ENTRY, STOP, TARGET, path)
    passed.append(check("managed: out at entry inside that bar", managed, ("moved_stop", 0.0)))
    passed.append(check("fixed: carried to the full stop", fixed, ("loss", -1.0)))

    print("\nbelow the +1R trigger nothing moves")
    path = bars((1.0, 1.0009, 0.9995, 1.0004), (1.0004, 1.0005, 0.9989, 0.9990))
    managed, fixed = both(LONG, ENTRY, STOP, TARGET, path)
    passed.append(check("+0.9R then the stop: -1R both ways", (managed, fixed), (("loss", -1.0), ("loss", -1.0))))

    print("\nshorts are the mirror image")
    path = bars((1.0, 1.0005, 0.9989, 0.9992), (0.9992, 1.0001, 0.9991, 0.9999),
                (0.9999, 1.0, 0.9984, 0.9986))
    managed, fixed = both(SHORT, ENTRY, 1.0010, 0.9985, path)
    passed.append(check("short managed: out at entry", managed, ("moved_stop", 0.0)))
    passed.append(check("short fixed: target", fixed, ("win", 1.5)))

    print("\ntrailing, for a target beyond +2R")
    path = bars((1.0, 1.0031, 0.9995, 1.0028), (1.0028, 1.0029, 1.0020, 1.0022))
    managed, fixed = both(LONG, ENTRY, STOP, 1.0050, path)
    passed.append(check("+3.1R: stop trails to +2.1R and is hit there", managed, ("moved_stop", 2.1)))
    passed.append(check("fixed: still open, marked to the last close", fixed, ("timeout", 2.2)))

    print("\nthe engine's switch is honoured")
    off = Settings(_env_file=None, trail_enabled=False)
    path = bars((1.0, 1.0011, 0.9995, 1.0008), (1.0008, 1.0009, 0.9999, 1.0003), (1.0003, 1.0016, 1.0001, 1.0014))
    managed, fixed = both(LONG, ENTRY, STOP, TARGET, path, off)
    passed.append(check("trail_enabled=false: managed == fixed", managed, fixed))

    print("\nit is the engine's code, not a copy")
    passed.append(check("StopManager drives DefaultExecutionEngine",
                        type(StopManager(defaults)._engine), DefaultExecutionEngine))
    manager = StopManager(defaults)
    a = simulate_outcome(LONG, ENTRY, STOP, TARGET, bars((1.0, 1.0011, 0.9995, 1.0008), (1.0008, 1.0009, 0.9999, 1.0)), manager)
    b = simulate_outcome(LONG, 2.0, 1.998, 2.003, bars((2.0, 2.0021, 1.9995, 2.0015), (2.0015, 2.0016, 1.9999, 2.0)), manager)
    passed.append(check("one manager, many trades: each keeps its own risk", (a, b), (("moved_stop", 0.0), ("moved_stop", 0.0))))

    print("\nthe fixed copy of a trade")
    o = TradeOutcome("EURUSD", LONG, T0, ENTRY, STOP, TARGET, "moved_stop", 0.0, -0.07, 0.07, 0.001,
                     fixed_result="win", fixed_gross_r=1.5)
    f = o.as_fixed()
    passed.append(check("as_fixed: fixed result, same cost", (f.result, f.gross_r, round(f.net_r, 6), f.cost_r),
                        ("win", 1.5, 1.43, 0.07)))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
