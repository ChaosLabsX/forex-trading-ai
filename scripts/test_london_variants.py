r"""The two London-breakout extensions move exactly one thing each, and never trade live by accident.

    .venv\Scripts\python.exe scripts\test_london_variants.py

london_breakout_crosses_v1 changes only the pairs; london_breakout_wide_v1
changes only the compression limit (1.75x instead of 1.5x). A test that moves
two things at once cannot say which one helped or hurt, so this pins both down:
the logic is the parent's own function, and on identical candles each variant
agrees with london_breakout_v1 everywhere except its one dimension.

It also proves the part that matters for real money. Plugins load on BOTH
engines, so the live engine sees these strategies too - they must arrive there
switched off, and be refused by the gate, while the live strategy stays armed.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.interfaces.strategy import StrategyContext                       # noqa: E402
from engine.core.models import AccountState, Candle, NewsEvent, Timeframe         # noqa: E402
from engine.gating import StrategyGate                                            # noqa: E402
from engine.indicators import atr                                                 # noqa: E402
from engine.plugins.strategies._common import (                                   # noqa: E402
    ALL_CURRENCIES, LONDON_CROSSES, UNIVERSE,
)
from engine.plugins.strategies.london_breakout_crosses_v1 import LondonBreakoutCrossesStrategy  # noqa: E402
from engine.plugins.strategies.london_breakout_v1 import LondonBreakoutStrategy   # noqa: E402
from engine.plugins.strategies.london_breakout_wide_v1 import LondonBreakoutWideStrategy  # noqa: E402

UTC = timezone.utc
TODAY = datetime(2026, 9, 16, tzinfo=UTC)
ACCOUNT = AccountState(balance=1000, equity=1000, margin_used=0, open_positions_count=0,
                       daily_pnl=0, consecutive_stop_losses_today=0)
NEW = ("london_breakout_crosses_v1", "london_breakout_wide_v1")


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def _bar(symbol, time, low, high):
    mid = (low + high) / 2
    return Candle(symbol, Timeframe.H1, time, mid, high, low, mid, 1.0)


def london_morning(symbol: str, asian_range: float) -> list[Candle]:
    """A day of ordinary 10-pip bars, an Asian session spanning `asian_range`,
    and a 07:00 bar that closes 3 pips above the Asian high - a fresh break."""
    base, bars = 1.10000, []
    for h in range(24):
        bars.append(_bar(symbol, TODAY - timedelta(hours=24 - h), base, base + 0.0010))
    for h in range(7):
        low = base + asian_range - 0.0010 if h == 3 else base
        bars.append(_bar(symbol, TODAY + timedelta(hours=h), low, low + 0.0010))
    top = base + asian_range
    bars.append(Candle(symbol, Timeframe.H1, TODAY + timedelta(hours=7),
                       top - 0.0004, top + 0.0004, top - 0.0006, top + 0.0003, 1.0))
    return bars


def morning_at_ratio(symbol: str, target: float) -> tuple[list[Candle], float]:
    """The morning whose Asian range / ATR(14) - computed exactly as the
    strategy computes it - lands closest to `target`."""
    best = None
    for pips in range(100, 400):
        bars = london_morning(symbol, pips / 100_000)
        ratio = (pips / 100_000) / atr(bars, 14)
        if best is None or abs(ratio - target) < abs(best[1] - target):
            best = (bars, ratio)
    return best


def run(strategy, symbol, bars, news=()):
    return strategy.evaluate(StrategyContext(symbol, {Timeframe.H1: bars}, ACCOUNT, [], tuple(news)))


def trade(evaluation):
    s = evaluation.signal
    return None if s is None else (s.direction, round(s.entry_price, 6), round(s.stop_loss, 6), round(s.take_profit, 6))


class FakeRegistry:
    """accounts / strategies / strategy_accounts, as PostgREST would filter them."""

    def __init__(self, account_type: str) -> None:
        self.key = f"icmarkets-{account_type}"
        self.tables = {
            "accounts": [{"key": self.key, "label": self.key, "account_type": account_type, "enabled": True}],
            "strategies": [{"name": "london_breakout_v1", "display_name": "london_breakout_v1",
                            "readiness": "almost_ready", "retired": False}],
            "strategy_accounts": [{"strategy_name": "london_breakout_v1", "account_key": self.key,
                                   "enabled": True, "live_override": account_type == "live"}],
        }

    def select(self, table, filters):
        rows = self.tables[table]
        for column, condition in filters.items():
            value = condition.split(".", 1)[1]
            rows = [r for r in rows if str(r.get(column)) == value]
        return [dict(r) for r in rows]

    def insert(self, table, rows, returning=False):
        self.tables[table].extend(dict(r) for r in rows)


def main() -> int:
    passed = []
    v1 = LondonBreakoutStrategy(settings=None)
    wide = LondonBreakoutWideStrategy(settings=None)
    crosses = LondonBreakoutCrossesStrategy(settings=None)

    print("each variant moves exactly one thing")
    passed.append(check("wide runs the parent's own evaluate()",
                        LondonBreakoutWideStrategy.evaluate is LondonBreakoutStrategy.evaluate, True))
    passed.append(check("crosses runs the parent's own evaluate()",
                        LondonBreakoutCrossesStrategy.evaluate is LondonBreakoutStrategy.evaluate, True))
    own = lambda cls: sorted(k for k in vars(cls) if not k.startswith("_"))  # _abc_impl is ABC machinery  # noqa: E731
    passed.append(check("wide overrides only its name and the limit", own(LondonBreakoutWideStrategy),
                        ["max_range_atr_multiple", "name"]))
    passed.append(check("crosses overrides only its name and the pairs", own(LondonBreakoutCrossesStrategy),
                        ["instruments", "name"]))
    passed.append(check("london_breakout_v1 is still 1.5x", v1.max_range_atr_multiple, 1.5))
    passed.append(check("wide is 1.75x", wide.max_range_atr_multiple, 1.75))
    passed.append(check("wide trades v1's 16 symbols", wide.instruments, UNIVERSE))
    passed.append(check("crosses keeps 1.5x", crosses.max_range_atr_multiple, 1.5))

    print("\nthe crosses are the pairs the premise applies to")
    passed.append(check("EURCHF GBPCHF EURCAD GBPCAD CADCHF", LONDON_CROSSES,
                        ("EURCHF", "GBPCHF", "EURCAD", "GBPCAD", "CADCHF")))
    passed.append(check("none already traded by v1", set(LONDON_CROSSES) & set(UNIVERSE), set()))
    asia = {c for sym in LONDON_CROSSES for c in ALL_CURRENCIES.get(sym, ())} & {"JPY", "AUD", "NZD"}
    passed.append(check("no Asian-session currency among them", asia, set()))
    passed.append(check("all covered by the news blackout",
                        all(sym in ALL_CURRENCIES for sym in LONDON_CROSSES), True))

    print("\nsame candles, three compression levels")
    quiet, r1 = morning_at_ratio("EURUSD", 1.40)
    middling, r2 = morning_at_ratio("EURUSD", 1.62)
    ordinary, r3 = morning_at_ratio("EURUSD", 1.95)
    print(f"  (ranges at {r1:.2f}x, {r2:.2f}x, {r3:.2f}x ATR)")
    a, b = run(v1, "EURUSD", quiet), run(wide, "EURUSD", quiet)
    passed.append(check(f"{r1:.2f}x: both fire, the identical trade",
                        (a.signal is not None, trade(a) == trade(b)), (True, True)))
    passed.append(check(f"{r1:.2f}x: each says its own limit",
                        ("<= 1.5x ATR" in a.signal.reason, "<= 1.75x ATR" in b.signal.reason) if a.signal and b.signal
                        else None, (True, True)))
    a, b = run(v1, "EURUSD", middling), run(wide, "EURUSD", middling)
    passed.append(check(f"{r2:.2f}x: v1 refuses, wide fires - the ONLY difference",
                        (a.signal is None, "(> 1.5x ATR" in a.reason, b.signal is not None), (True, True, True)))
    a, b = run(v1, "EURUSD", ordinary), run(wide, "EURUSD", ordinary)
    passed.append(check(f"{r3:.2f}x: both refuse", (a.signal, b.signal, "(> 1.75x ATR" in b.reason),
                        (None, None, True)))

    print("\nthe crosses behave exactly as v1 would on their candles")
    bars, _ = morning_at_ratio("EURCHF", 1.40)
    passed.append(check("EURCHF: same trade as v1's logic", trade(run(crosses, "EURCHF", bars)),
                        trade(run(v1, "EURCHF", bars))))
    passed.append(check("EURCHF: it is a trade", run(crosses, "EURCHF", bars).signal is not None, True))
    chf_news = [NewsEvent("SNB rate decision", TODAY + timedelta(hours=7, minutes=10), "CHF", "high")]
    jpy_news = [NewsEvent("BoJ rate decision", TODAY + timedelta(hours=7, minutes=10), "JPY", "high")]
    passed.append(check("EURCHF: a CHF high-impact event blacks it out",
                        run(crosses, "EURCHF", bars, chf_news).signal, None))
    passed.append(check("EURCHF: a JPY event does not",
                        run(crosses, "EURCHF", bars, jpy_news).signal is not None, True))

    print("\nregistered, and loaded by the engine config")
    from engine.config import Settings
    from engine.registry import build_engine, load_plugin
    passed.append(check("both load through the registry",
                        [load_plugin("strategy", key, None).name for key in NEW], list(NEW)))
    names = [s.name for s in build_engine(settings=Settings(test_mode=True)).strategies]
    passed.append(check("both listed in config/plugins.yaml", all(key in names for key in NEW), True))
    passed.append(check("london_breakout_v1 still listed", "london_breakout_v1" in names, True))

    print("\nREAL MONEY: on the live account they arrive switched off")
    known = ["london_breakout_v1", *NEW]
    live = FakeRegistry("live")
    gate = StrategyGate(live, types.SimpleNamespace(account_key=live.key, live_trading_enabled=True))
    gate.sync_strategies(known)
    links = {r["strategy_name"]: r["enabled"] for r in live.tables["strategy_accounts"]}
    passed.append(check("linked to live with enabled=false", [links.get(k) for k in NEW], [False, False]))
    result = gate.gate(known, force=True)
    passed.append(check("the live gate refuses both", sorted(set(NEW) - result.eligible), sorted(NEW)))
    passed.append(check("london_breakout_v1 stays armed on live", "london_breakout_v1" in result.eligible, True))

    print("\n...and on the demo lab they trade")
    demo = FakeRegistry("demo")
    gate = StrategyGate(demo, types.SimpleNamespace(account_key=demo.key, live_trading_enabled=False))
    gate.sync_strategies(known)
    passed.append(check("both eligible on demo", set(NEW) <= gate.gate(known, force=True).eligible, True))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
