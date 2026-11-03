r"""Orders go in seconds after the bar closes, sized never above the risk setting.

    .venv\Scripts\python.exe scripts\test_order_timing.py

Two fixes from 2026-11-03, both about trades going in the way they were planned:

1. Timing. The candle pass used to run every 60s from whenever the engine
   started - 45-55s after each hourly close in practice - and an AI review of
   one symbol held up every later symbol's order by ~12s. Now the pass runs a
   few seconds after each minute turns, and reviews wait until every order of
   the pass is in.
2. Sizing. Lots were sized from the candle close the signal was priced from.
   The market order fills at the live price; when that has moved away from the
   stop, the planned lots risked more than the setting (up to 1.4x, measured).
   Now lots are the smaller of the plan and the live-price size.
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.loop as loop_mod                                                      # noqa: E402
from engine.config import Settings                                                 # noqa: E402
from engine.core.interfaces.strategy import StrategyEvaluation                     # noqa: E402
from engine.core.models import AccountState, Candle, Direction, Signal, Timeframe  # noqa: E402
from engine.gating import Gate                                                     # noqa: E402
from engine.loop import EngineLoop, candle_pass_due                                # noqa: E402
from engine.plugins.brokers import mt5_broker                                      # noqa: E402
from engine.plugins.risk.default_risk_engine import DefaultRiskEngine              # noqa: E402
from engine.sizing import SymbolLimits                                             # noqa: E402

UTC = timezone.utc
H = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)  # an hourly close


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def bare_loop(**attrs) -> EngineLoop:
    loop = EngineLoop.__new__(EngineLoop)
    for k, v in attrs.items():
        setattr(loop, k, v)
    return loop


def passes_between(start: datetime, seconds: int) -> list[datetime]:
    """Drive the real _tick() every 2s on a fake wall clock; return when each
    candle pass ran."""
    clock = [start]
    ran = []
    loop = bare_loop(_connected=True, _flat=False, _last_command_poll=1e18, _last_heartbeat=1e18,
                     _last_manage=1e18, _last_evaluation=1e18, _last_candle_minute=None, _pending_reviews=[],
                     _settings=types.SimpleNamespace(evaluation_interval_minutes=30))
    loop._ensure_connected = lambda: None
    loop._is_lab = lambda: False
    loop._maybe_send_daily_summary = lambda: None
    loop._refresh_market_data_and_evaluate = lambda: ran.append(clock[0])

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    real_dt = loop_mod.datetime
    loop_mod.datetime = FakeDatetime
    try:
        for _ in range(seconds // 2):
            loop._tick()
            clock[0] += timedelta(seconds=2)
    finally:
        loop_mod.datetime = real_dt
    return ran


class FakeBroker:
    def __init__(self, live=None, raises=False):
        self.live, self.raises, self.asked = live, raises, 0

    def clock_is_provisional(self):
        return False

    def server_now(self):
        return None

    def get_symbol_limits(self, symbol):
        # EURUSD-like: $10 a pip a lot, 0.01-lot steps
        return SymbolLimits(volume_min=0.01, volume_max=100.0, volume_step=0.01, value_per_price_per_lot=100_000.0)

    def calc_margin(self, symbol, direction, lots, price):
        return 1.0

    def market_entry_price(self, symbol, direction):
        self.asked += 1
        if self.raises:
            raise RuntimeError("no tick")
        return self.live


def size(direction, entry, stop, live=None, equity=10_000.0, raises=False, test_mode=False):
    settings = Settings(_env_file=None, test_mode=test_mode, default_risk_pct=0.75, max_risk_pct=2.0,
                        max_margin_use_pct=50.0, max_concurrent_trades=4, live_trading_enabled=False)
    broker = FakeBroker(live, raises)
    tp = entry + (0.003 if direction == Direction.LONG else -0.003)
    signal = Signal("london_breakout_v1", "EURUSD", direction, Timeframe.H1, entry, stop, tp, "test")
    account = AccountState(balance=equity, equity=equity, margin_used=0.0, open_positions_count=0,
                           daily_pnl=0.0, consecutive_stop_losses_today=0)
    decision = DefaultRiskEngine(settings).validate_signal(signal, account, [], broker)
    return decision, broker


def main() -> int:
    logging.disable(logging.CRITICAL)
    passed = []

    print("the candle pass runs just after the minute turns")
    passed.append(check(":00:01 - not yet (the new bar's first tick may not be in)", candle_pass_due(H + timedelta(seconds=1), None), False))
    passed.append(check(":00:03 - due", candle_pass_due(H + timedelta(seconds=3), None), True))
    passed.append(check("same minute, already run - not again", candle_pass_due(H + timedelta(seconds=40), H), False))
    passed.append(check("next minute :01:03 - due", candle_pass_due(H + timedelta(minutes=1, seconds=3), H), True))
    passed.append(check("a pass that overran into the next minute is followed at once",
                        candle_pass_due(H + timedelta(minutes=1, seconds=30), H), True))
    ran = passes_between(H - timedelta(seconds=30), 200)  # 08:59:30 -> 09:02:50, ticking every 2s
    passed.append(check("the real _tick: a pass at start-up, then one a minute",
                        [r.strftime("%H:%M:%S") for r in ran], ["08:59:30", "09:00:04", "09:01:04", "09:02:04"]))
    passed.append(check("...every pass after start-up within 5s of the minute turning (was up to 59s)",
                        all(r.second <= 5 for r in ran[1:]), True))
    passed.append(check("the 09:00 close is acted on at 09:00:04 at the latest", ran[1] <= H + timedelta(seconds=4), True))
    old_style_start = H - timedelta(seconds=15)  # an engine started at :45 used to pass at :45 every minute
    passed.append(check("...whatever second the engine started at",
                        all(r.second <= 5 for r in passes_between(old_style_start, 130)[1:]), True))

    print("\nAI reviews wait until every order of the pass is in")
    events = []
    strategy = types.SimpleNamespace(
        name="london_breakout_v1", instruments=("EURGBP", "GBPJPY"), required_timeframes=(Timeframe.H1,),
        evaluate=lambda ctx: StrategyEvaluation(
            Signal("london_breakout_v1", ctx.symbol, Direction.SHORT, Timeframe.H1, 1.0, 1.01, 0.985, "break"),
            "break"),
    )
    loop = bare_loop(_paused=False, _engine=types.SimpleNamespace(strategies=[strategy]),
                     _gate=types.SimpleNamespace(gate=lambda names: Gate(frozenset({"london_breakout_v1"}), {}, None)),
                     _logged_blocks={}, _last_evaluated_bar={}, _ticket_owner={}, _pending_reviews=[])
    loop._log_signal = lambda name, symbol, ev: {"EURGBP": 1, "GBPJPY": 2}[symbol]
    loop._route_through_risk_engine = lambda name, sig, acct, pos, sid: (events.append(("order", sig.symbol)), (True, "ok"))[1]
    loop._update_signal_risk = lambda *a: None
    loop._review_with_ai = lambda sid, sig, ctx: events.append(("review", sig.symbol))
    bars = {Timeframe.H1: [Candle("X", Timeframe.H1, H - timedelta(hours=1), 1, 1, 1, 1, 1)]}
    for symbol in ("EURGBP", "GBPJPY"):
        loop._evaluate_strategies(symbol, bars, object(), [], ())
    passed.append(check("during the pass: both orders, no review yet", events, [("order", "EURGBP"), ("order", "GBPJPY")]))
    loop._run_pending_reviews()
    passed.append(check("after it: both reviews, in order", events[2:], [("review", "EURGBP"), ("review", "GBPJPY")]))
    passed.append(check("the queue is empty afterwards", loop._pending_reviews, []))

    print("\nsizing: never more lots than planned, never more risk than the setting")
    d, b = size(Direction.SHORT, 1.1000, 1.1020)
    passed.append(check("no live price available: the planned size, as before (0.37 lots on a 20-pip stop)",
                        d.order.lot_size, 0.37))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, live=1.1000)
    passed.append(check("live price = signal price: same size", d.order.lot_size, 0.37))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, live=1.0986)
    passed.append(check("short, price moved AWAY from the stop (34-pip stop now): fewer lots (0.22)",
                        (d.order.lot_size, "sized from the live price" in d.reason), (0.22, True)))
    d, _ = size(Direction.LONG, 1.1000, 1.0980, live=1.1012)
    passed.append(check("long, the same move the other way: fewer lots (0.23)", d.order.lot_size, 0.23))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, live=1.1014)
    passed.append(check("price moved TOWARD the stop (6-pip stop now): the plan, not more lots",
                        d.order.lot_size, 0.37))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, live=1.1025)
    passed.append(check("price already past the stop: no trade",
                        (d.approved, "already past the stop" in d.reason), (False, True)))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, live=1.0970, equity=333.34)
    passed.append(check("even the minimum lot at the live price would exceed the budget: no trade",
                        (d.approved, "not sized at the live price" in d.reason), (False, True)))
    d, _ = size(Direction.SHORT, 1.1000, 1.1020, raises=True)
    passed.append(check("reading the live price fails: falls back to the plan", d.order.lot_size, 0.37))
    d, b = size(Direction.SHORT, 1.1000, 1.1020, live=1.0986, test_mode=True)
    passed.append(check("demo lab (TEST_MODE): broker minimum, live price not even asked",
                        (d.order.lot_size, b.asked), (0.01, 0)))

    print("\nthe MT5 adapter reads the side a market order fills at")
    adapter = mt5_broker.MT5BrokerAdapter.__new__(mt5_broker.MT5BrokerAdapter)
    real_tick = mt5_broker.mt5.symbol_info_tick
    try:
        mt5_broker.mt5.symbol_info_tick = lambda s: types.SimpleNamespace(ask=1.1002, bid=1.1000)
        passed.append(check("buy -> the ask, sell -> the bid",
                            (adapter.market_entry_price("EURUSD", Direction.LONG),
                             adapter.market_entry_price("EURUSD", Direction.SHORT)), (1.1002, 1.1)))
        mt5_broker.mt5.symbol_info_tick = lambda s: None
        passed.append(check("no tick: None (sizing falls back to the plan)",
                            adapter.market_entry_price("EURUSD", Direction.LONG), None))
        mt5_broker.mt5.symbol_info_tick = lambda s: types.SimpleNamespace(ask=0.0, bid=0.0)
        passed.append(check("a zero price: None, never used", adapter.market_entry_price("EURUSD", Direction.SHORT), None))
    finally:
        mt5_broker.mt5.symbol_info_tick = real_tick

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
