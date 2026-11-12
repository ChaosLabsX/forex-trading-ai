r"""max_concurrent_trades binds INSIDE a candle pass, not only between passes.

    .venv\Scripts\python.exe scripts\test_concurrent_cap.py

Found 2026-11-13 in the live account's own records. The pass reads the open
positions once, before the first symbol, and every symbol was checked against
that snapshot - so signals firing on the same bar each saw "0 open". On
2026-11-10 08:00 the live account (MAX_CONCURRENT_TRADES=2) opened four
correlated longs on one bar (EURJPY, EURAUD, GBPAUD, CADJPY); all four stopped
out. Three weeks earlier the same cap had refused a third trade - because that
signal happened to arrive one pass later.

This drives the real pass - EngineLoop._refresh_market_data_and_evaluate, the
real DefaultRiskEngine and DefaultExecutionEngine - against a fake broker and a
fake Supabase, replaying that morning.
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings                                                  # noqa: E402
from engine.core.interfaces.strategy import StrategyEvaluation                      # noqa: E402
from engine.core.models import (                                                    # noqa: E402
    AccountState, Candle, Direction, Position, PositionStatus, Signal, Timeframe,
)
from engine.gating import AccountInfo, Gate                                         # noqa: E402
from engine.loop import EngineLoop                                                  # noqa: E402
from engine.plugins.execution.default_execution_engine import DefaultExecutionEngine  # noqa: E402
from engine.plugins.risk.default_risk_engine import DefaultRiskEngine               # noqa: E402
from engine.sizing import SymbolLimits                                              # noqa: E402

UTC = timezone.utc
BAR = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)  # the bar that closed at 08:00
MORNING = ("EURJPY", "EURAUD", "GBPAUD", "CADJPY")  # what fired on 2026-11-10, in UNIVERSE order


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


class FakeBroker:
    def __init__(self, refuse: set[str] | None = None):
        self.positions: list[Position] = []
        self.refuse = refuse or set()
        self._ticket = 1000

    def get_account_state(self):
        return AccountState(balance=229.40, equity=229.40, margin_used=0.0,
                            open_positions_count=len(self.positions), daily_pnl=0.0,
                            consecutive_stop_losses_today=0)

    def get_open_positions(self):
        return list(self.positions)

    def clock_is_provisional(self):
        return False

    def server_now(self):
        return None

    def get_symbol_limits(self, symbol):
        return SymbolLimits(volume_min=0.01, volume_max=100.0, volume_step=0.01, value_per_price_per_lot=100_000.0)

    def get_price_value_per_lot(self, symbol):
        return 100_000.0

    def calc_margin(self, symbol, direction, lots, price):
        return 1.0

    def market_entry_price(self, symbol, direction):
        return None

    def place_order(self, symbol, direction, lot_size, stop_loss, take_profit):
        if symbol in self.refuse:
            raise RuntimeError("order refused: market closed (retcode 10018)")
        self._ticket += 1
        position = Position(id=str(self._ticket), symbol=symbol, direction=direction, lot_size=lot_size,
                            entry_price=1.1000, stop_loss=stop_loss, take_profit=take_profit,
                            status=PositionStatus.OPEN, opened_at=datetime.now(UTC))
        self.positions.append(position)
        return position

    def get_closed_position_breakdown(self, ticket):
        return None


class FakeSupabase:
    """Just enough PostgREST: a trades table the loop can read its OPEN rows from."""

    def __init__(self):
        self.trades: list[dict] = []
        self.risk_reasons: list[tuple[bool, str]] = []
        self._signal_id = 0

    def insert(self, table, rows, returning=False):
        if table == "trades":
            self.trades.extend(dict(r) for r in rows)
        if table == "signals":
            self._signal_id += 1
            return [{"id": self._signal_id}]
        return None

    def select(self, table, filters):
        if table == "trades" and filters.get("status") == "eq.OPEN":
            return [t for t in self.trades if t["status"] == "OPEN"]
        return []

    def update(self, table, filters, patch):
        if table == "signals":
            self.risk_reasons.append((patch["risk_approved"], patch["risk_reason"]))
        if table == "trades":
            ticket = filters["mt5_ticket"].removeprefix("eq.")
            for t in self.trades:
                if t["mt5_ticket"] == ticket:
                    t.update(patch)


def fires_everywhere(name: str, symbols=MORNING):
    return types.SimpleNamespace(
        name=name, instruments=symbols, required_timeframes=(Timeframe.H1,),
        evaluate=lambda ctx: StrategyEvaluation(
            # a 10-pip stop: $1.00 at the 0.01-lot minimum, inside the $1.72 budget
            Signal(name, ctx.symbol, Direction.LONG, Timeframe.H1, 1.1000, 1.0990, 1.1015, "break"), "break"),
    )


def build(cap: int, strategies, test_mode=False, refuse=None):
    settings = Settings(_env_file=None, test_mode=test_mode, default_risk_pct=0.75, max_risk_pct=2.0,
                        max_margin_use_pct=25.0, max_concurrent_trades=cap,
                        live_trading_enabled=not test_mode, account_key="icmarkets-live")
    broker, supabase = FakeBroker(refuse), FakeSupabase()
    clock = [BAR]
    market_data = types.SimpleNamespace(
        # one closed bar + the forming one, as copy_rates_from_pos returns them
        get_candles=lambda symbol, tf, count: [
            Candle(symbol, tf, clock[0], 1.1, 1.1, 1.1, 1.1, 1),
            Candle(symbol, tf, clock[0] + timedelta(hours=1), 1.1, 1.1, 1.1, 1.1, 1),
        ])
    names = [s.name for s in strategies]
    loop = EngineLoop.__new__(EngineLoop)
    loop._engine = types.SimpleNamespace(
        strategies=strategies, broker=broker, market_data=market_data, news_provider=None,
        risk_engine=DefaultRiskEngine(settings), execution_engine=DefaultExecutionEngine(settings),
        notifications=[], ai_provider=None)
    loop._supabase = supabase
    loop._settings = settings
    loop._account_key = settings.account_key
    loop._gate = types.SimpleNamespace(
        gate=lambda known, force=False: Gate(frozenset(names), {}, None),
        risk_pct_for=lambda name: 0.75,
        account=lambda: AccountInfo("icmarkets-live", "Live", "live", True))
    loop._instruments = tuple(dict.fromkeys(sym for s in strategies for sym in s.instruments))
    loop._unavailable_instruments = set()
    loop._market_data_block = None
    loop._last_persisted_bar = {}
    loop._paused = False
    loop._logged_blocks = {}
    loop._last_evaluated_bar = {}
    loop._ticket_owner = {}
    loop._opened_this_pass = []
    loop._pending_reviews = []

    def run_pass(hours_later: int = 0) -> list[str]:
        """One real candle pass on the bar `hours_later` after 08:00; the symbols it opened."""
        clock[0] = BAR + timedelta(hours=hours_later)
        before = {p.id for p in broker.positions}
        loop._refresh_market_data_and_evaluate()
        return [p.symbol for p in broker.positions if p.id not in before]

    return loop, broker, supabase, run_pass


def main() -> int:
    logging.disable(logging.CRITICAL)
    passed = []

    print("2026-11-10 08:00 replayed: four signals on one bar, live cap 2")
    loop, broker, supabase, run_pass = build(2, [fires_everywhere("london_breakout_v1")])
    opened = run_pass()
    passed.append(check("only the first two are opened (was all four)", opened, ["EURJPY", "EURAUD"]))
    passed.append(check("the other two are refused by the cap, with the reason recorded",
                        [(ok, reason) for ok, reason in supabase.risk_reasons[2:]],
                        [(False, "max concurrent trades reached (2)")] * 2))
    passed.append(check("two trades rows, both owned by the strategy",
                        [(t["symbol"], t["strategy_name"]) for t in supabase.trades],
                        [("EURJPY", "london_breakout_v1"), ("EURAUD", "london_breakout_v1")]))

    print("\nthe next passes: no double counting, and a freed slot is usable")
    passed.append(check("next bar, both still open: nothing opened", run_pass(1), []))
    passed.append(check("...and each position is counted once (2, not 4)",
                        len(loop._positions_of("london_breakout_v1", broker.get_open_positions())), 2))
    broker.positions.pop(0)  # EURJPY hits its stop at the broker
    passed.append(check("one closes: exactly one more is opened on the following bar", run_pass(2), ["EURJPY"]))
    passed.append(check("never more than the cap open at once", len(broker.positions), 2))

    print("\neach strategy has its own budget (the lab's isolation rule)")
    loop, broker, supabase, run_pass = build(
        2, [fires_everywhere("london_breakout_v1"), fires_everywhere("ema_trend_v1")])
    run_pass()
    owners = [loop._ticket_owner[p.id] for p in broker.positions]
    passed.append(check("two strategies firing on the same four symbols: two each",
                        (owners.count("london_breakout_v1"), owners.count("ema_trend_v1")), (2, 2)))

    print("\na refused order does not use up a slot")
    loop, broker, supabase, run_pass = build(2, [fires_everywhere("london_breakout_v1")], refuse={"EURJPY"})
    passed.append(check("EURJPY refused by the broker: the next two symbols are opened",
                        run_pass(), ["EURAUD", "GBPAUD"]))

    print("\nthe demo lab (TEST_MODE, cap 4) is held to its cap the same way")
    six = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "EURGBP")
    loop, broker, supabase, run_pass = build(4, [fires_everywhere("london_breakout_v1", six)], test_mode=True)
    passed.append(check("six signals on one bar: four opened", len(run_pass()), 4))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
