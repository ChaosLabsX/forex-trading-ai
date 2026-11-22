r"""Broker outage alerts: told about the ones that matter, quiet about the rest.

    python scripts\test_broker_alerts.py

A week of heartbeats (2026-11-15..22) showed nine broker outages, eight at the
weekend and one a 2-minute blip at the nightly rollover - each sent as two
Telegram alerts. The owner asked for quiet. This drives the REAL
EngineLoop._ensure_connected with a scripted clock and broker, and the real
_tick for the heartbeat, through each case that matters:

  - start-up: no broker alert (ENGINE STARTED covers it);
  - a weekday blip under 3 minutes: no alert, and still reconnects;
  - a weekday outage past 3 minutes: one DISCONNECTED, one RECONNECTED;
  - a weekend outage of any length: nothing;
  - a weekend outage still going after the open: told, once it matters;
  - the heartbeat keeps going while the broker is down, so the watchdog's
    ENGINE SILENT means the engine, not the broker.
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.loop as loop_module                  # noqa: E402
from engine.gating import AccountInfo              # noqa: E402
from engine.loop import EngineLoop                 # noqa: E402

THU = datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)   # market open
SAT = datetime(2026, 11, 21, 13, 40, tzinfo=timezone.utc)  # market closed
SUN_BEFORE_OPEN = datetime(2026, 11, 22, 21, 50, tzinfo=timezone.utc)  # opens 22:00


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want!r}\n         actual  : {got!r}")
    return ok


class FakeBroker:
    def __init__(self) -> None:
        self.up = True        # can the link be (re)established?
        self.linked = False   # is it established right now?

    def is_connected(self):
        return self.linked

    def connect(self):
        if not self.up:
            raise ConnectionError("no route to trade server")
        self.linked = True

    def drop(self):
        self.up = self.linked = False


class Sim:
    """A loop with a scripted monotonic clock and wall clock, both of which
    the loop's own time.sleep() (the reconnect backoff) advances."""

    def __init__(self, start: datetime) -> None:
        self.mono, self.wall = 1_000.0, start
        self.broker = FakeBroker()
        self.sent: list[str] = []
        loop = EngineLoop.__new__(EngineLoop)
        loop._engine = types.SimpleNamespace(
            broker=self.broker,
            notifications=[types.SimpleNamespace(notify=lambda e: self.sent.append(e.message))])
        loop._gate = types.SimpleNamespace(account=lambda: AccountInfo("icmarkets-live", "Live", "live", True))
        loop._account_key = "icmarkets-live"
        loop._connected = False
        loop._backoff_index = 0
        loop._ever_connected = False
        loop._down_since = None
        loop._down_alerted = False
        self.loop = loop

    def _advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)

    def run(self, seconds: float, step: float = 2.0) -> None:
        """Tick _ensure_connected for `seconds` of simulated time."""
        sim = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return sim.wall

        real_time, real_dt = loop_module.time, loop_module.datetime
        loop_module.time = types.SimpleNamespace(monotonic=lambda: sim.mono, sleep=sim._advance)
        loop_module.datetime = Clock
        try:
            end = self.mono + seconds
            while self.mono < end:
                self.loop._ensure_connected()
                self._advance(step)
        finally:
            loop_module.time, loop_module.datetime = real_time, real_dt

    def heads(self) -> list[str]:
        return [m.splitlines()[0] for m in self.sent]


def outage(start: datetime, down_seconds: float) -> Sim:
    sim = Sim(start)
    sim.run(60)                  # start-up, settled
    sim.broker.drop()
    sim.run(down_seconds)
    sim.broker.up = True
    sim.run(120)                 # back, and settled
    return sim


def main() -> int:
    logging.disable(logging.CRITICAL)
    r = []

    print("start-up")
    sim = Sim(THU)
    sim.run(60)
    r.append(check("connects with no broker alert", (sim.loop._connected, sim.sent), (True, [])))

    print("weekday blip (the 2-minute rollover drop of 19 Nov)")
    sim = outage(THU, 120)
    r.append(check("no alert, reconnected", (sim.sent, sim.loop._connected), ([], True)))

    print("weekday outage past 3 minutes")
    sim = outage(THU, 600)
    r.append(check("one DISCONNECTED, then one RECONNECTED",
                   sim.heads(), ["⚠️ BROKER DISCONNECTED", "🔌 BROKER RECONNECTED"]))
    if len(sim.sent) == 2:
        r.append(check("...saying how long it had been down", sim.sent[0].splitlines()[1:],
                       ["LIVE", "down 3 min  ·  reconnecting"]))
        last = sim.sent[1].splitlines()[-1]
        r.append(check("...and how long it lasted", last.startswith("after ") and last.endswith(" min")
                       and int(last.split()[1]) >= 10, True))

    print("weekend outage (the 15-minute drop of Sat 21 Nov)")
    sim = outage(SAT, 15 * 60)
    r.append(check("nothing at all", sim.sent, []))
    sim = outage(SAT, 6 * 3600)
    r.append(check("even six hours: nothing", sim.sent, []))

    print("weekend outage still going after the Sunday open")
    sim = outage(SUN_BEFORE_OPEN, 20 * 60)
    r.append(check("told once the market opens, then the all-clear",
                   sim.heads(), ["⚠️ BROKER DISCONNECTED", "🔌 BROKER RECONNECTED"]))
    if sim.sent:
        mins = int(sim.sent[0].splitlines()[-1].split()[1])
        # Dropped at 21:51 (after the 60s start-up), the market opened 22:00.
        r.append(check("...counting from when it really went down: 9 min at the open", mins, 9))

    print("the heartbeat keeps going while the broker is down (real _tick)")
    beats = []
    loop = EngineLoop.__new__(EngineLoop)
    for k, v in dict(_connected=False, _flat=True, _last_command_poll=0.0, _last_heartbeat=0.0,
                     _last_manage=0.0, _last_evaluation=1e12, _last_candle_minute=None,
                     _pending_reviews=[], _settings=types.SimpleNamespace(evaluation_interval_minutes=30)).items():
        setattr(loop, k, v)
    loop._ensure_connected = lambda: None                 # the broker stays down
    loop._is_lab = lambda: False
    loop._send_heartbeat = lambda: beats.append(loop._connected)
    loop._maybe_send_market_alert = lambda: None
    loop._run_pending_reviews = lambda: None
    for name in ("_process_commands", "_refresh_market_data_and_evaluate", "_manage_open_positions"):
        setattr(loop, name, lambda n=name: (_ for _ in ()).throw(AssertionError(f"{n} ran while disconnected")))
    clock = [10_000.0]
    real_time = loop_module.time
    loop_module.time = types.SimpleNamespace(monotonic=lambda: clock[0])
    try:
        for _ in range(150):                               # 5 minutes of 2s ticks
            loop._tick()
            clock[0] += 2
    finally:
        loop_module.time = real_time
    r.append(check("5 minutes disconnected: 5 heartbeats, each saying broker down", beats, [False] * 5))

    passed = sum(r)
    print(f"\n{passed}/{len(r)} passed")
    return 0 if passed == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
