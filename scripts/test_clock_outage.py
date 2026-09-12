r"""What the engine does when the broker's clock cannot be measured.

    .venv\Scripts\python.exe scripts\test_clock_outage.py

ServerClock refuses to guess the broker's UTC offset when EURUSD has not ticked
since the process started - a weekend restart, in practice. Refusing is correct:
guessing from a stale tick is what put the demo lab 31 hours into the future on
2026-09-06. But every per-cycle path that touches the clock has to handle that
refusal calmly, and on 2026-09-12 two of them did not:

  * _refresh_market_data_and_evaluate  - 60 tracebacks an hour
  * _manage_open_positions             - 720 an hour (every 5s), and ONLY on an
                                         account holding positions, so the demo
                                         lab drowned while the flat live engine
                                         looked perfectly healthy

That asymmetry is the lesson this file exists to keep: a path can be broken for
months and invisible, because whether it fires depends on account state rather
than on the bug. So drive them ALL, not the one that happened to be reported.

Asserts on the LOG, because the log is what the fix changes: the refusal must
cost one line per outage, never a traceback per cycle, and must still speak up
when the reason changes.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The MetaTrader5 package needs a local terminal and is Windows-only; the code
# under test never calls it here, so a stub keeps this runnable anywhere.
sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

from engine.loop import EngineLoop                                  # noqa: E402
from engine.plugins.brokers.mt5_time import ServerTimeUnavailable   # noqa: E402

REASON = ("the broker's UTC offset is unknown - EURUSD is not ticking. "
          "Refusing to timestamp data from a guess.")
CYCLES = 60


def _raise(*_args, **_kwargs):
    raise ServerTimeUnavailable(REASON)


class DeadClockBroker:
    """A broker whose clock has never been measured. get_open_positions() fails
    exactly as the real one does when positions exist: _to_position() stamps
    opened_at through the clock."""
    get_open_positions = _raise
    get_account_state = _raise
    close_position = _raise


class DeadClockMarketData:
    get_candles = _raise
    get_latest_tick = _raise


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def build_loop() -> EngineLoop:
    """The real EngineLoop with only the state these methods touch. Deliberately
    not a full construction - that needs Supabase, MT5 and a config file, and
    the point is to exercise the methods, not the wiring."""
    loop = object.__new__(EngineLoop)
    loop._engine = types.SimpleNamespace(
        market_data=DeadClockMarketData(),
        broker=DeadClockBroker(),
        execution_engine=object(),
        news_provider=None,
        notifications=[],
    )
    loop._unavailable_instruments = set()
    loop._market_data_block = None
    loop._instruments = ("EURUSD", "GBPUSD", "USDJPY")
    loop._last_persisted_bar = {}
    loop._supabase = None
    return loop


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}")
        print(f"         actual  : {got}")
    return ok


def main() -> int:
    handler = Collect()
    logger = logging.getLogger("engine.loop")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    passed = []
    for label, drive in (
        ("evaluation path", lambda lp: lp._refresh_market_data_and_evaluate()),
        ("stop management", lambda lp: lp._manage_open_positions()),
    ):
        loop = build_loop()
        handler.records.clear()
        for _ in range(CYCLES):
            drive(loop)
        tracebacks = [r for r in handler.records if r.exc_info]
        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        print(f"{label}: {CYCLES} cycles with an unmeasurable clock")
        passed.append(check("no tracebacks", len(tracebacks), 0))
        passed.append(check("one line for the whole outage", len(warnings), 1))
        if warnings:
            print(f"         -> {warnings[0].getMessage()}")

        # A permanent hush would be its own bug: a NEW reason must still speak.
        loop._engine.broker.get_open_positions = loop._engine.broker.get_account_state = (
            lambda *_a, **_k: (_ for _ in ()).throw(ServerTimeUnavailable("a different reason")))
        loop._engine.market_data.get_candles = (
            lambda *_a, **_k: (_ for _ in ()).throw(ServerTimeUnavailable("a different reason")))
        drive(loop)
        passed.append(check("speaks again when the reason changes",
                            len([r for r in handler.records if r.levelno == logging.WARNING]), 2))
        print()

    print("emergency close-all with an unmeasurable clock")
    loop = build_loop()
    sent: list[str] = []
    loop._engine.notifications = [types.SimpleNamespace(
        notify=lambda event: sent.append(event.message))]
    handler.records.clear()
    # Caught, not allowed to propagate: an UNFIXED engine raises here, and a
    # test that dies inside its own failure report tells you nothing.
    raised: Exception | None = None
    try:
        loop._emergency_close_all()
    except Exception as exc:
        raised = exc
    passed.append(check("does not raise at the caller", type(raised).__name__, "NoneType"))
    passed.append(check("says plainly that nothing was closed",
                        any("Nothing was closed" in m for m in sent), True))

    logger.removeHandler(handler)
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
