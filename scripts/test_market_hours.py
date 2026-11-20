r"""Market open/close alerts: the right instant, the right Jakarta time, one sender.

    python scripts\test_market_hours.py

The FX week runs Sunday 17:00 to Friday 17:00 New York, which moves an hour in
UTC (and in Jakarta) with US daylight saving - so the schedule is checked on
both sides of both switches. The alert itself is driven through the REAL
EngineLoop._maybe_send_market_alert with a scripted clock: silent at startup,
one alert per change, the close carrying the live week pair by pair, and
nothing at all from the demo engine.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.loop as loop_module                                       # noqa: E402
from engine import market_hours as mh                                   # noqa: E402
from engine.gating import AccountInfo                                   # noqa: E402
from engine.loop import EngineLoop                                      # noqa: E402
from engine.reporting import market_closed, market_opened               # noqa: E402


def utc(*a) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want!r}\n         actual  : {got!r}")
    return ok


class FakeSupabase:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def select(self, table, filters):
        self.asked.append((table, dict(filters)))
        return [dict(r) for r in self.rows]


class Recorder:
    def __init__(self):
        self.sent = []

    def notify(self, event):
        self.sent.append(event)


def fake_loop(account_type: str, rows: list[dict]):
    loop = EngineLoop.__new__(EngineLoop)
    recorder = Recorder()
    key = f"icmarkets-{account_type}"
    loop._engine = types.SimpleNamespace(notifications=[recorder])
    loop._gate = types.SimpleNamespace(account=lambda: AccountInfo(key, key, account_type, True))
    loop._supabase = FakeSupabase(rows)
    loop._account_key = key
    loop._market_was_open = None
    return loop, recorder


def at(loop, when: datetime) -> None:
    """Run the real alert check with the loop's clock set to `when`."""
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    real = loop_module.datetime
    loop_module.datetime = Clock
    try:
        loop._maybe_send_market_alert()
    finally:
        loop_module.datetime = real


def main() -> int:
    r = []

    print("the FX week, in UTC, across US daylight saving")
    r.append(check("winter Fri 21:59 UTC: open", mh.is_open(utc(2026, 11, 20, 21, 59)), True))
    r.append(check("winter Fri 22:00 UTC (17:00 EST): closed", mh.is_open(utc(2026, 11, 20, 22, 0)), False))
    r.append(check("winter Sun 21:59 UTC: closed", mh.is_open(utc(2026, 11, 22, 21, 59)), False))
    r.append(check("winter Sun 22:00 UTC: open", mh.is_open(utc(2026, 11, 22, 22, 0)), True))
    r.append(check("summer Fri 20:59 UTC: open", mh.is_open(utc(2026, 7, 10, 20, 59)), True))
    r.append(check("summer Fri 21:00 UTC (17:00 EDT): closed", mh.is_open(utc(2026, 7, 10, 21, 0)), False))
    r.append(check("summer Sun 21:00 UTC: open", mh.is_open(utc(2026, 7, 12, 21, 0)), True))
    r.append(check("Wednesday: open", mh.is_open(utc(2026, 11, 18, 3, 0)), True))
    r.append(check("DST starts Sun 8 Mar: Friday closed at 22:00 UTC (EST)",
                   mh.next_close(utc(2026, 3, 6, 12)), utc(2026, 3, 6, 22)))
    r.append(check("...and Sunday opens at 21:00 UTC (EDT)", mh.next_open(utc(2026, 3, 7, 12)), utc(2026, 3, 8, 21)))
    r.append(check("DST ends Sun 1 Nov: Friday closed at 21:00 UTC (EDT)",
                   mh.next_close(utc(2026, 10, 30, 12)), utc(2026, 10, 30, 21)))
    r.append(check("...and Sunday opens at 22:00 UTC (EST)", mh.next_open(utc(2026, 10, 31, 12)), utc(2026, 11, 1, 22)))

    print("next event, in Jakarta time (UTC+7, 12-hour, no year)")
    closed = utc(2026, 11, 20, 22, 0)
    r.append(check("closed Fri -> opens", mh.jakarta(mh.next_open(closed)), "5:00 AM - 23 Nov"))
    r.append(check("open Sun -> closes", mh.jakarta(mh.next_close(utc(2026, 11, 22, 22, 0))), "5:00 AM - 28 Nov"))
    r.append(check("summer open -> 4:00 AM", mh.jakarta(mh.next_open(utc(2026, 7, 10, 21, 0))), "4:00 AM - 13 Jul"))
    r.append(check("noon is 12 PM", mh.jakarta(utc(2026, 11, 20, 5, 30)), "12:30 PM - 20 Nov"))
    r.append(check("midnight is 12 AM, next day", mh.jakarta(utc(2026, 11, 20, 17, 5)), "12:05 AM - 21 Nov"))
    r.append(check("the week that closed began Sunday 22:00 UTC", mh.week_start(closed), utc(2026, 11, 15, 22)))
    r.append(check("...however late the close is noticed (Saturday noon)",
                   mh.week_start(utc(2026, 11, 21, 12, 0)), utc(2026, 11, 15, 22)))
    r.append(check("...or on Sunday before the open",
                   mh.week_start(utc(2026, 11, 22, 21, 0)), utc(2026, 11, 15, 22)))

    print("the messages")
    r.append(check("open", market_opened("5:00 AM - 28 Nov"), "🔓 MARKET OPEN  ·  closes 5:00 AM - 28 Nov"))
    week = [{"symbol": "EURGBP", "realized_pnl": -2.10}, {"symbol": "USDCAD", "realized_pnl": 8.05},
            {"symbol": "EURGBP", "realized_pnl": -2.10}, {"symbol": "USDCAD", "realized_pnl": 0.05},
            {"symbol": "NZDUSD", "realized_pnl": None}]
    r.append(check("closed, with the week best pair first (unknown P&L left out)", market_closed("5:00 AM - 23 Nov", week),
                   "🔒 MARKET CLOSED  ·  opens 5:00 AM - 23 Nov\n"
                   "This week: 4 trades  ·  net +$3.90\n"
                   "USDCAD  2  ·  +$8.10\n"
                   "EURGBP  2  ·  -$4.20"))
    r.append(check("closed, quiet week", market_closed("5:00 AM - 23 Nov", []),
                   "🔒 MARKET CLOSED  ·  opens 5:00 AM - 23 Nov\nThis week: no trades"))

    print("the real loop: one alert per change, from the live engine only")
    loop, sent = fake_loop("live", [{"symbol": "USDCAD", "realized_pnl": 5.0}])
    at(loop, utc(2026, 11, 20, 21, 0))
    r.append(check("startup (open): silent", len(sent.sent), 0))
    at(loop, utc(2026, 11, 20, 21, 59))
    r.append(check("still open: silent", len(sent.sent), 0))
    at(loop, utc(2026, 11, 20, 22, 0, 2))
    r.append(check("the close: one alert", [e.message.splitlines()[0] for e in sent.sent],
                   ["🔒 MARKET CLOSED  ·  opens 5:00 AM - 23 Nov"]))
    r.append(check("...with this account's week", sent.sent[-1].message.splitlines()[1:],
                   ["This week: 1 trade  ·  net +$5.00", "USDCAD  1  ·  +$5.00"]))
    table, filters = loop._supabase.asked[-1]
    r.append(check("...read from closed, non-void live trades since Sunday's open",
                   (table, filters["account_key"], filters["status"], filters["void_reason"], filters["closed_at"]),
                   ("trades", "eq.icmarkets-live", "eq.CLOSED", "is.null", "gte.2026-11-15T22:00:00+00:00")))
    at(loop, utc(2026, 11, 21, 12, 0))
    r.append(check("Saturday: silent", len(sent.sent), 1))
    at(loop, utc(2026, 11, 22, 22, 0, 2))
    r.append(check("the open: one alert", sent.sent[-1].message, "🔓 MARKET OPEN  ·  closes 5:00 AM - 28 Nov"))
    r.append(check("two alerts in all", len(sent.sent), 2))

    restarted, after = fake_loop("live", [])
    at(restarted, utc(2026, 11, 21, 12, 0))
    r.append(check("restart over the weekend: no stale 'closed' alert", len(after.sent), 0))

    demo, demo_sent = fake_loop("demo", [])
    for t in (utc(2026, 11, 20, 21, 0), utc(2026, 11, 20, 22, 1), utc(2026, 11, 22, 22, 1)):
        at(demo, t)
    r.append(check("demo engine: never sends", len(demo_sent.sent), 0))

    passed = sum(r)
    print(f"\n{passed}/{len(r)} passed")
    return 0 if passed == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
