r"""Per-pair risk reaches the sizing, and nothing outsized gets through.

    python scripts\test_symbol_risk.py

strategy_accounts.symbol_risk_pct (migration 0018) lets one strategy risk a
different % per pair. Real money depends on four things, each exercised on its
real code path: the gate reads the column (and survives its absence, before
the migration is applied), a bad entry falls back rather than guesses, the
loop asks for the SIGNAL's pair, and the risk engine sizes at that % - clamped
to max_risk_pct.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.config import Settings                                         # noqa: E402
from engine.core.models import (AccountState, Direction, RiskDecision,     # noqa: E402
                                Signal, Timeframe)
from engine.gating import StrategyGate, parse_symbol_risk                  # noqa: E402
from engine.loop import EngineLoop                                         # noqa: E402
from engine.plugins.risk.default_risk_engine import DefaultRiskEngine      # noqa: E402
from test_order_timing import FakeBroker                                   # noqa: E402

PAIRS = {"USDCAD": 7, "NZDUSD": 6, "USDCHF": 6, "USDJPY": 6, "GBPJPY": 5, "EURJPY": 5, "CHFJPY": 5}


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


class FakeRegistry:
    """The three registries as PostgREST returns them. `column=False` is the
    database before migration 0018: the key is simply absent from the row."""

    def __init__(self, symbol_risk=None, column=True) -> None:
        link = {"strategy_name": "london_breakout_v1", "account_key": "icmarkets-live",
                "enabled": True, "live_override": True, "risk_pct": 2.0}
        if column:
            link["symbol_risk_pct"] = symbol_risk
        self.tables = {
            "accounts": [{"key": "icmarkets-live", "label": "Live", "account_type": "live", "enabled": True}],
            "strategies": [{"name": "london_breakout_v1", "display_name": "london_breakout_v1",
                            "readiness": "not_ready", "retired": False}],
            "strategy_accounts": [link],
        }

    def select(self, table, filters):
        rows = self.tables[table]
        for column, condition in filters.items():
            value = condition.split(".", 1)[1]
            rows = [r for r in rows if str(r.get(column)) == value]
        return [dict(r) for r in rows]


def gate_for(registry: FakeRegistry) -> StrategyGate:
    gate = StrategyGate(registry, types.SimpleNamespace(account_key="icmarkets-live", live_trading_enabled=True))
    gate.gate(["london_breakout_v1"], force=True)
    return gate


def sized(risk_pct: float) -> RiskDecision:
    settings = Settings(_env_file=None, test_mode=False, live_trading_enabled=False)
    signal = Signal("london_breakout_v1", "USDCAD", Direction.LONG, Timeframe.H1, 1.1000, 1.0980, 1.1030, "t")
    account = AccountState(balance=10_000.0, equity=10_000.0, margin_used=0.0, open_positions_count=0,
                           daily_pnl=0.0, consecutive_stop_losses_today=0)
    return DefaultRiskEngine(settings).validate_signal(signal, account, [], FakeBroker(live=1.1000),
                                                       risk_pct=risk_pct)


def main() -> int:
    results = []

    print("the column is parsed, and a bad entry falls back rather than guesses")
    results.append(check("valid object", parse_symbol_risk({"usdcad": 7, "NZDUSD": 6.5}, "s"),
                         {"USDCAD": 7.0, "NZDUSD": 6.5}))
    results.append(check("zero, negative, text and true are dropped",
                         parse_symbol_risk({"A": 0, "B": -3, "C": "7", "D": True, "E": 5}, "s"), {"E": 5.0}))
    results.append(check("not an object: ignored", parse_symbol_risk([7], "s"), {}))
    results.append(check("NULL: nothing", parse_symbol_risk(None, "s"), {}))

    print("the gate answers per pair")
    gate = gate_for(FakeRegistry(PAIRS))
    results.append(check("USDCAD -> 7", gate.risk_pct_for("london_breakout_v1", "USDCAD"), 7.0))
    results.append(check("USDJPY -> 6", gate.risk_pct_for("london_breakout_v1", "USDJPY"), 6.0))
    results.append(check("CHFJPY -> 5", gate.risk_pct_for("london_breakout_v1", "CHFJPY"), 5.0))
    results.append(check("EURGBP (not listed) -> the strategy's risk_pct, 2",
                         gate.risk_pct_for("london_breakout_v1", "EURGBP"), 2.0))
    results.append(check("lower-case symbol still matches", gate.risk_pct_for("london_breakout_v1", "usdcad"), 7.0))
    results.append(check("no symbol -> the strategy's risk_pct", gate.risk_pct_for("london_breakout_v1"), 2.0))
    results.append(check("before migration 0018 (no column): risk_pct for every pair",
                         gate_for(FakeRegistry(column=False)).risk_pct_for("london_breakout_v1", "USDCAD"), 2.0))
    results.append(check("column NULL: risk_pct for every pair",
                         gate_for(FakeRegistry(None)).risk_pct_for("london_breakout_v1", "USDCAD"), 2.0))

    print("the loop asks for the signal's own pair (real _route_through_risk_engine)")
    asked = []

    class RecordingRiskEngine:
        def validate_signal(self, signal, account_state, open_positions, broker, risk_pct=None):
            asked.append(risk_pct)
            return RiskDecision(approved=False, reason="recorded")

    loop = EngineLoop.__new__(EngineLoop)
    loop._engine = types.SimpleNamespace(risk_engine=RecordingRiskEngine(), broker=object(), notifications=[])
    loop._gate = gate
    for symbol in ("USDCAD", "EURGBP"):
        sig = Signal("london_breakout_v1", symbol, Direction.LONG, Timeframe.H1, 1.0, 0.99, 1.02, "t")
        loop._route_through_risk_engine("london_breakout_v1", sig, None, [])
    results.append(check("USDCAD signal sized at 7, EURGBP at 2", asked, [7.0, 2.0]))

    print("the risk engine sizes at that % - and never above max_risk_pct")
    defaults = Settings(_env_file=None)
    results.append(check("max_risk_pct is 7", defaults.max_risk_pct, 7.0))
    results.append(check("max_margin_use_pct is 100", defaults.max_margin_use_pct, 100.0))
    for pct, want in ((7.0, "risking 7.00%"), (6.0, "risking 6.00%"), (2.0, "risking 2.00%"),
                      (9.0, "risking 7.00%")):
        d = sized(pct)
        label = f"{pct:g}% asked -> {want}" + (" (clamped)" if pct > 7 else "")
        results.append(check(label, (d.approved, d.reason.startswith(want)), (True, True)))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
