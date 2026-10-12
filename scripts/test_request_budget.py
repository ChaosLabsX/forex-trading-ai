r"""The engine makes far fewer Supabase requests, and close-all is as fast as ever.

    .venv\Scripts\python.exe scripts\test_request_budget.py

Supabase logs every request, and log ingestion took the free plan to 4.16 GB of
its 1 GB (2026-10). Two engines sent ~200,000 requests a day: 48 candle writes a
minute each, for a table nothing reads back, and a dashboard-command poll every
2 seconds each. These checks pin the new budget and, above all, the one thing
it must not cost: on a live account holding a position, emergency close-all is
still polled every 2 seconds.
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.loop as loop_mod                                                     # noqa: E402
from engine.core.interfaces.market_data import MarketDataUnavailable              # noqa: E402
from engine.core.models import Candle, Timeframe                                  # noqa: E402
from engine.loop import EngineLoop, candles_to_persist, command_poll_interval     # noqa: E402

T0 = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def bars(n: int, start: datetime = T0) -> list[Candle]:
    return [Candle("EURUSD", Timeframe.H1, start + timedelta(hours=i), 1, 1, 1, 1, 1) for i in range(n)]


class FakeSupabase:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def upsert(self, table, rows, on_conflict):
        if self.fail:
            raise RuntimeError("supabase down")
        self.calls.append((table, len(rows), on_conflict))


def bare_loop(**attrs) -> EngineLoop:
    """An EngineLoop without __init__ - only the attributes a method under test reads."""
    loop = EngineLoop.__new__(EngineLoop)
    for k, v in attrs.items():
        setattr(loop, k, v)
    return loop


def polls_in(seconds: int, is_lab: bool, flat: bool) -> int:
    """Run the real _tick() against a fake clock, one tick every 2s (the loop's
    sleep), and count how often it polls commands."""
    clock = [1_000.0]
    polls = []
    loop = bare_loop(
        _connected=True, _flat=flat, _last_command_poll=0.0,
        _last_heartbeat=1e12, _last_candle_refresh=1e12, _last_manage=1e12, _last_evaluation=1e12,
        _settings=types.SimpleNamespace(evaluation_interval_minutes=30),
    )
    loop._ensure_connected = lambda: None
    loop._is_lab = lambda: is_lab
    loop._process_commands = lambda: polls.append(clock[0])
    loop._maybe_send_daily_summary = lambda: None
    real_time = loop_mod.time
    loop_mod.time = types.SimpleNamespace(monotonic=lambda: clock[0])
    try:
        for _ in range(seconds // loop_mod.POLL_INTERVAL_SECONDS):
            loop._tick()
            clock[0] += loop_mod.POLL_INTERVAL_SECONDS
    finally:
        loop_mod.time = real_time
    return len(polls)


def main() -> int:
    logging.disable(logging.CRITICAL)  # the failure cases log tracebacks on purpose
    passed = []

    print("dashboard commands: close-all is never slower where money is at stake")
    passed.append(check("live, holding a position: every 2s", command_poll_interval(False, False), 2))
    passed.append(check("live, flat: every 10s", command_poll_interval(False, True), 10))
    passed.append(check("demo lab: every 15s", command_poll_interval(True, False), 15))
    passed.append(check("the real _tick, live holding, 1 hour: 1,800 polls (as before)", polls_in(3600, False, False), 1800))
    passed.append(check("the real _tick, live flat, 1 hour: 360 polls", polls_in(3600, False, True), 360))
    # 15s on a 2s tick lands every 16s
    passed.append(check("the real _tick, demo, 1 hour: 225 polls", polls_in(3600, True, False), 225))

    print("\n'flat' is believed only when a position read says so")
    def manage(result):
        broker = types.SimpleNamespace(get_open_positions=result)
        md = types.SimpleNamespace(get_latest_tick=lambda s: None)
        ex = types.SimpleNamespace(manage_open_position=lambda p, t, b: None)
        loop = bare_loop(_engine=types.SimpleNamespace(broker=broker, execution_engine=ex, market_data=md),
                         _flat=None, _market_data_block=None)
        loop._note_block = lambda where, exc: None
        loop._flat = "before"
        loop._manage_open_positions()
        return loop._flat
    def raise_(exc):
        def f():
            raise exc
        return f
    pos = types.SimpleNamespace(symbol="EURUSD", id="1")
    passed.append(check("no positions -> flat", manage(lambda: []), True))
    passed.append(check("a position -> holding", manage(lambda: [pos]), False))
    passed.append(check("read failed -> holding (unknown never counts as flat)", manage(raise_(RuntimeError("x"))), False))
    passed.append(check("market shut -> unchanged (positions can't change)",
                        manage(raise_(MarketDataUnavailable("closed"))), "before"))
    passed.append(check("a new engine starts as holding",
                        "self._flat = False" in Path(loop_mod.__file__).read_text(encoding="utf-8"), True))

    print("\ncandles: closed bars only, each stored once")
    window = bars(300)  # 299 closed + the forming bar
    first = candles_to_persist(window, None)
    passed.append(check("first pass: the 299 closed bars, not the forming one",
                        (len(first), first[-1].time), (299, window[-2].time)))
    passed.append(check("same pass again: nothing", candles_to_persist(window, first[-1].time), []))
    later = bars(301)  # an hour on: one more bar has closed
    passed.append(check("an hour later: exactly the bar that closed",
                        [c.time for c in candles_to_persist(later, first[-1].time)], [later[-2].time]))
    passed.append(check("only the forming bar exists: nothing", candles_to_persist(bars(1), None), []))

    print("\none request per pass, marks move only after a good write")
    rows = [{"n": i} for i in range(2500)]
    marks = {("EURUSD", Timeframe.H1): T0}
    db = FakeSupabase()
    loop = bare_loop(_supabase=db, _last_persisted_bar={})
    loop._persist_candles(rows, marks)
    passed.append(check("2,500 rows -> 3 requests of <= 1,000", [n for _, n, _ in db.calls], [1000, 1000, 500]))
    passed.append(check("marks advanced", loop._last_persisted_bar, marks))
    bad = bare_loop(_supabase=FakeSupabase(fail=True), _last_persisted_bar={})
    bad._persist_candles(rows, marks)
    passed.append(check("failed write: marks unchanged, so the next pass retries", bad._last_persisted_bar, {}))
    quiet = FakeSupabase()
    bare_loop(_supabase=quiet, _last_persisted_bar={})._persist_candles([], {})
    passed.append(check("nothing new: no request at all", quiet.calls, []))

    print("\nonly the demo lab stores candles")
    src = Path(loop_mod.__file__).read_text(encoding="utf-8")
    passed.append(check("persist = self._is_lab()", "persist = self._is_lab()" in src, True))
    passed.append(check("no per-symbol candle upsert left in the pass",
                        src.count('"candles", rows[start : start + CANDLE_PERSIST_CHUNK]'), 1))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
