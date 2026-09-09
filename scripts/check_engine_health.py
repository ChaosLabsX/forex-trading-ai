"""Is each engine alive, armed, and actually evaluating?

Answers the question the logs cannot: "there are no trades - is something
broken, or is there simply nothing to trade?" A blocked strategy and a working
one that found no setup both produce silence, and an absence of errors cannot
tell them apart.

Four things it reads, in the order they can fail:

  1. HEARTBEAT - is the process alive, is the broker attached, and is guard 1
     (LIVE_TRADING_ENABLED) on?
  2. CLOCKS - is each engine stamping bars with the right time? The quietest
     failure here: a stale-tick measurement of the broker's UTC offset put the
     demo lab's bars 31 hours ahead, and nothing errored for three days.
  3. GATE - guards 2/3/4, through the engine's own StrategyGate, so this can
     never drift from what the engine will actually do.
  4. ACTIVITY - the signals table stores a row for EVERY evaluation, fired or
     not, with the reason. Non-firing rows are positive proof a strategy is
     running; the demo lab, which runs the identical code, is the control for
     whether live is behaving normally.

WHY GUARD 1 COMES FROM THE HEARTBEAT. It is an environment variable read once
at process start, and for the live engine it lives in .env.live on the VPS - so
Settings() here would report it off wherever this script is run from, and
declare an armed account safe. The engine publishes its own state in every
heartbeat instead. That is not a workaround: the running process is the only
thing that knows, and a config file is at best a claim about it.

Read-only. Safe to run at any time, from anywhere holding the .env:

    python scripts/check_engine_health.py
    python scripts/check_engine_health.py --days 7

Output is deliberately ASCII - the Windows console this runs on is cp1252, and
a health check that garbles its own separators invites being ignored.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.gating import StrategyGate
from engine.supabase_client import SupabaseClient

# Beyond this the engine is not merely quiet, it is gone: heartbeats go out
# every 60s, so three missed in a row is not a slow cycle.
STALE_HEARTBEAT_SECONDS = 240

# A reason beginning "outside" means the bar fell outside the strategy's
# trading window. True, but it only proves the loop is turning - the
# evaluations that reached the strategy's actual premise are the informative
# ones, and they are swamped ~7:1 by these.
WINDOW_PREFIX = "outside"

# Reasons carry the bar they judged, e.g. "(bar hour 09:00 UTC)" - the only
# record of what time each engine THOUGHT it was.
BAR_HOUR = re.compile(r"bar hour (\d{2}):00 UTC")


def _age(iso: str) -> timedelta:
    return datetime.now(timezone.utc) - datetime.fromisoformat(iso)


def _fmt_age(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    return f"{seconds / 3600:.1f}h ago"


def heartbeats(supabase: SupabaseClient, accounts: list[dict]) -> dict[str, bool | None]:
    """Print engine liveness; return each account's guard-1 state (None = unknown)."""
    guard1: dict[str, bool | None] = {}
    print("ENGINES")
    for account in accounts:
        key = account["key"]
        guard1[key] = None
        rows = supabase.select(
            "engine_heartbeats",
            {
                "account_key": f"eq.{key}",
                "select": "status,broker_connected,detail,created_at",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        if not rows:
            print(f"   {key:18} NEVER heartbeated")
            continue
        hb = rows[0]
        age = _age(hb["created_at"])
        dead = age.total_seconds() > STALE_HEARTBEAT_SECONDS
        state = "DEAD" if dead else hb["status"].upper()
        broker = "broker attached" if hb["broker_connected"] else "BROKER DETACHED"

        note = ""
        if not dead and hb["detail"] == "live_trading=on":
            guard1[key] = True
            note = "  |  guard 1 ON - real orders armed"
        elif not dead and hb["detail"] == "live_trading=off":
            guard1[key] = False
            note = "  |  guard 1 off"
        print(f"   {key:18} {state:8} {_fmt_age(age):>9}  {broker}{note}")
    print()
    return guard1


def clocks(supabase: SupabaseClient, accounts: list[dict]) -> None:
    """Is each engine stamping bars with the right time?

    A wrong server-time offset is the quietest failure this system has: no
    error, no alert, every log line plausible, and the strategies quietly
    judging the wrong bars. It cost the demo lab three days in September 2026.

    Two independent tells. A candle dated in the future is proof on its own -
    no correct engine can write one. And every signals row records the wall
    clock it was written at plus, in its reason text, the bar hour it judged;
    the SMALLEST lag across recent rows is 1 hour for a healthy engine (H1
    strategies judge the bar that just closed, H4 ones lag up to 4), so
    anything else is the offset being wrong by that much.
    """
    now = datetime.now(timezone.utc)
    print("CLOCKS")

    future = supabase.select(
        "candles",
        {
            "time": f"gt.{now.isoformat()}",
            "select": "symbol,timeframe,time",
            "order": "time.desc",
            "limit": "1",
        },
    )
    if future:
        f = future[0]
        ahead = (datetime.fromisoformat(f["time"]) - now).total_seconds() / 3600
        print(f"   candles table holds FUTURE-DATED bars - newest {f['symbol']} {f['timeframe']}"
              f" at {f['time'][:19]} ({ahead:+.1f}h). Some engine's clock is wrong.")

    for account in accounts:
        rows = supabase.select(
            "signals",
            {
                "account_key": f"eq.{account['key']}",
                "select": "created_at,reason",
                "order": "created_at.desc",
                "limit": "200",
            },
        )
        lags = [
            (int(r["created_at"][11:13]) - int(m.group(1))) % 24
            for r in rows
            if (m := BAR_HOUR.search(r["reason"]))
        ]
        if not lags:
            print(f"   {account['key']:18} no dated evaluations in the last 200 rows")
            continue
        lag = min(lags)
        if lag == 1:
            print(f"   {account['key']:18} OK - bars stamped correctly")
        else:
            # (1 - lag) mod 24 is how far AHEAD the bars are stamped, which is
            # what a reader can check against a chart. The raw lag is not.
            print(f"   {account['key']:18} DRIFTED - bars stamped {(1 - lag) % 24}h ahead of "
                  f"where they belong. Restart this engine while the market is OPEN.")
    print()


def gate_report(
    supabase: SupabaseClient,
    settings: Settings,
    account: dict,
    known: list[str],
    guard1: bool | None,
) -> None:
    """Guards 2/3/4 through the engine's own gate - never a second copy of the rule."""
    # Guard 1 is supplied from the heartbeat, not from this machine's .env; see
    # the module docstring. Unknown means no recent heartbeat, so report guards
    # 2/3/4 alone rather than inventing a verdict for a guard we cannot see.
    gate = StrategyGate(
        supabase,
        settings.model_copy(
            update={"account_key": account["key"], "live_trading_enabled": guard1 is not False}
        ),
    ).gate(known, force=True)

    source = {True: "on (from heartbeat)", False: "OFF (from heartbeat)"}.get(
        guard1, "unknown - no recent heartbeat, guards 2/3/4 only"
    )
    print(f"GATE  |  {account['key']}  |  guard 1: {source}")
    for name in sorted(known):
        if name in gate.eligible:
            risk = gate.risk_pct.get(name)
            risk_text = f"{risk}%" if risk is not None else f"{settings.default_risk_pct}% (default)"
            print(f"   {name:24} ELIGIBLE - will place real orders  |  risk {risk_text}")
        else:
            print(f"   {name:24} blocked - {gate.blocked.get(name, 'not eligible')}")
    print()


def activity(supabase: SupabaseClient, accounts: list[dict], known: list[str], days: int) -> None:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    print(f"ACTIVITY  |  last {days} day(s)")
    print(f"   {'account':18} {'strategy':24} {'evaluations':>12} {'fired':>7}")
    live_names: dict[str, list[str]] = {}
    for account in accounts:
        for name in known:
            base = {
                "account_key": f"eq.{account['key']}",
                "strategy_name": f"eq.{name}",
                "created_at": f"gte.{since}",
            }
            total = supabase.count("signals", base)
            if total == 0:
                continue
            live_names.setdefault(account["key"], []).append(name)
            fired = supabase.count("signals", {**base, "fired": "is.true"})
            print(f"   {account['key']:18} {name:24} {total:>12} {fired:>7}")
    print()

    for account in accounts:
        for name in live_names.get(account["key"], []):
            rows = supabase.select(
                "signals",
                {
                    "account_key": f"eq.{account['key']}",
                    "strategy_name": f"eq.{name}",
                    "created_at": f"gte.{since}",
                    "select": "reason",
                    "order": "created_at.desc",
                    "limit": "1000",
                },
            )
            reasons = Counter(
                r["reason"] for r in rows if not r["reason"].startswith(WINDOW_PREFIX)
            )
            if not reasons:
                print(f"   {account['key']} / {name}: only out-of-window evaluations in this sample")
                continue
            print(f"   {account['key']} / {name} - why no trade:")
            for reason, n in reasons.most_common(5):
                print(f"      {n:5d}  {reason[:78]}")
            print()


def last_fired(supabase: SupabaseClient) -> None:
    rows = supabase.select(
        "signals",
        {
            "fired": "is.true",
            "select": "created_at,account_key,strategy_name,symbol,direction",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    if not rows:
        print("Nothing has ever fired.")
        return
    r = rows[0]
    print(
        f"Last signal ANYWHERE: {_fmt_age(_age(r['created_at']))}  "
        f"{r['strategy_name']} {r['symbol']} {r['direction']} on {r['account_key']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Engine liveness, live gate, and evaluation activity.")
    parser.add_argument("--days", type=int, default=3, help="activity window (default 3)")
    args = parser.parse_args()

    settings = Settings()
    supabase = SupabaseClient(settings)
    # Names come from the strategies table, not build_engine(): the registry
    # imports the MT5 plugins, which only exist on the VPS, and this script is
    # meant to run from anywhere holding the .env.
    known = [
        s["name"]
        for s in supabase.select("strategies", {"select": "name,retired"})
        if not s["retired"]
    ]

    accounts = sorted(
        supabase.select("accounts", {"select": "key,label,account_type,enabled"}),
        key=lambda a: a["account_type"],
    )

    guard1 = heartbeats(supabase, accounts)
    clocks(supabase, accounts)
    for account in accounts:
        if account["account_type"] == "live":
            gate_report(supabase, settings, account, known, guard1[account["key"]])
    activity(supabase, accounts, known, args.days)
    last_fired(supabase)


if __name__ == "__main__":
    main()
