r"""Does the daily summary tell the truth about what the live account can do?

    .venv\Scripts\python.exe scripts\test_daily_summary.py

Every daily summary from 2026-09-05 to 2026-09-14 warned "no strategy is Ready -
live trading would place no trades by design" - while london_breakout_v1 was
cleared to place real orders on a live_override. The digest re-derived the live
gate and left the override out, the same mistake the dashboard's label made.
Wrong in the worst direction: it reassured the user that real money was idle.

It now asks the engine's own rule (gating.strategy_block_reason). This drives
build_daily_summary against a fake Supabase in each state that matters and
asserts on the WARNINGS, because that is the line a user acts on.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.reporting import build_daily_summary  # noqa: E402

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)


class FakeSupabase:
    def __init__(self, *, readiness: str, enabled: bool, override: bool, guard1: str | None,
                 live_account: bool = True) -> None:
        self.tables = {
            "accounts": [{"key": "icmarkets-demo", "account_type": "demo", "enabled": True}]
            + ([{"key": "icmarkets-live", "account_type": "live", "enabled": True}] if live_account else []),
            "strategies": [{"name": "london_breakout_v1", "retired": False, "readiness": readiness}],
            "strategy_accounts": [
                {"strategy_name": "london_breakout_v1", "account_key": "icmarkets-demo",
                 "enabled": True, "live_override": False},
            ] + ([{"strategy_name": "london_breakout_v1", "account_key": "icmarkets-live",
                   "enabled": enabled, "live_override": override}] if live_account else []),
        }
        self.guard1 = guard1

    def select(self, table: str, filters: dict) -> list[dict]:
        if table == "engine_heartbeats":
            live = filters.get("account_key") == "eq.icmarkets-live"
            return [{"created_at": NOW.isoformat(), "status": "running",
                     "detail": self.guard1 if live else None}]
        return self.tables.get(table, [])


def warnings_of(**state) -> list[str]:
    text = build_daily_summary(FakeSupabase(**state), None, now=NOW)
    if "WARNINGS" not in text:
        return []
    found = [line.strip(" •") for line in text.split("WARNINGS", 1)[1].strip().splitlines()]
    # The section always renders; "none" is its empty marker, not a warning.
    return [] if found == ["none"] else found


def check(label: str, got: list[str], must: str | None) -> bool:
    joined = " | ".join(got)
    ok = (not got) if must is None else (must in joined)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {'no warnings' if must is None else repr(must)}")
        print(f"         actual  : {joined or 'no warnings'}".encode("ascii", "replace").decode())
    return ok


def main() -> int:
    passed = [
        check("override on an unproven strategy says so - the real 2026-09-14 state",
              warnings_of(readiness="almost_ready", enabled=True, override=True, guard1="live_trading=on"),
              "trading real money on override"),
        check("...and never claims live would place no trades",
              [w for w in warnings_of(readiness="almost_ready", enabled=True, override=True,
                                      guard1="live_trading=on") if "place no trades" in w],
              None),
        check("nothing cleared says live will not trade",
              warnings_of(readiness="almost_ready", enabled=True, override=False, guard1="live_trading=on"),
              "no strategy is cleared for live"),
        check("cleared but guard 1 off says no real order can be placed",
              warnings_of(readiness="almost_ready", enabled=True, override=True, guard1="live_trading=off"),
              "LIVE_TRADING_ENABLED is off"),
        check("toggle off beats an override",
              warnings_of(readiness="almost_ready", enabled=False, override=True, guard1="live_trading=on"),
              "no strategy is cleared for live"),
        check("a genuinely Ready strategy raises no warning",
              warnings_of(readiness="ready", enabled=True, override=False, guard1="live_trading=on"),
              None),
        check("no live account raises no live warning",
              warnings_of(readiness="not_ready", enabled=True, override=False, guard1=None,
                          live_account=False),
              None),
    ]
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
