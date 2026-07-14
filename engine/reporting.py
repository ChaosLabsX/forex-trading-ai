"""Human-facing Telegram copy: strategy lifecycle events and the daily digest.

Kept apart from the evaluator/loop so the wording can change without touching
any decision logic, and so every message can be unit-tested without a broker,
a database, or a network.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone

from engine.evaluator import ALMOST_READY, NOT_READY, READY, Evaluation
from engine.stats import TradeStats

logger = logging.getLogger("engine.reporting")

_RANK = {NOT_READY: 0, ALMOST_READY: 1, READY: 2}
_LABEL = {NOT_READY: "Not ready", ALMOST_READY: "Almost ready", READY: "READY"}
STALE_HEARTBEAT_SECONDS = 5 * 60


def _money(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"


def stats_line(s: TradeStats) -> str:
    bits = [f"{s.trades_count} trades"]
    if s.win_rate is not None:
        bits.append(f"{s.win_rate:.0f}% win")
    if s.expectancy_r is not None:
        bits.append(f"exp {s.expectancy_r:+.3f}R")
    if s.ci_low is not None and s.ci_high is not None:
        bits.append(f"CI [{s.ci_low:+.2f},{s.ci_high:+.2f}]")
    if s.profit_factor is not None:
        bits.append(f"PF {s.profit_factor:.2f}")
    if s.max_drawdown_r is not None:
        bits.append(f"maxDD {s.max_drawdown_r:.1f}R")
    return "  ·  ".join(bits)


def format_readiness_change(strategy: dict, previous: str | None, evaluation: Evaluation) -> str:
    promoted = _RANK.get(evaluation.verdict, 0) > _RANK.get(previous or NOT_READY, 0)
    name = strategy.get("display_name") or strategy.get("name")
    lines = [
        f"{'⬆️' if promoted else '⚠️'} STRATEGY {'PROMOTED' if promoted else 'DEMOTED'}  ·  {name}",
        f"{_LABEL.get(previous or NOT_READY, previous)} → {_LABEL.get(evaluation.verdict, evaluation.verdict)}",
        f"Why: {evaluation.reason}",
        stats_line(evaluation.stats),
    ]
    if evaluation.verdict == READY:
        lines.append("Now eligible for live trading (if you enable it on the live account).")
    elif previous == READY:
        lines.append("Live trading for this strategy stops now unless you explicitly override it.")
    return "\n".join(lines)


def _utc_day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), dtime.min, tzinfo=timezone.utc)


def parse_daily_time(raw: str) -> dtime | None:
    try:
        hour, minute = raw.split(":")
        return dtime(int(hour), int(minute), tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        logger.error("invalid daily_summary_utc_time %r - expected HH:MM", raw)
        return None


def build_daily_summary(supabase, account_block: str | None, now: datetime | None = None) -> str:
    """Whole-system digest, read straight from Supabase so it covers every
    account regardless of which engine process sends it."""
    now = now or datetime.now(timezone.utc)
    day_start = _utc_day_start(now)
    day_start_iso = day_start.isoformat()

    accounts = supabase.select("accounts", {})
    strategies = supabase.select("strategies", {})
    links = supabase.select("strategy_accounts", {})

    lines = [f"📊 DAILY SUMMARY  ·  {now.date().isoformat()} (UTC)", ""]
    warnings: list[str] = []

    # --- engines -----------------------------------------------------------
    lines.append("ENGINES")
    for account in accounts:
        beats = supabase.select(
            "engine_heartbeats",
            {"account_key": f"eq.{account['key']}", "order": "created_at.desc", "limit": "1"},
        )
        if not beats:
            lines.append(f"  {account['key']}: no heartbeat ever received")
            if account["enabled"]:
                warnings.append(f"{account['key']} has never sent a heartbeat")
            continue
        beat = beats[0]
        age = (now - datetime.fromisoformat(beat["created_at"].replace("Z", "+00:00"))).total_seconds()
        state = beat.get("status", "?")
        if age > STALE_HEARTBEAT_SECONDS:
            lines.append(f"  {account['key']}: OFFLINE (last beat {int(age // 60)}m ago)")
            if account["enabled"]:
                warnings.append(f"{account['key']} engine looks offline")
        else:
            lines.append(f"  {account['key']}: {state} ({int(age)}s ago)")

    # --- strategies --------------------------------------------------------
    by_verdict = {NOT_READY: 0, ALMOST_READY: 0, READY: 0}
    for strategy in strategies:
        if strategy.get("retired"):
            continue
        by_verdict[strategy.get("readiness", NOT_READY)] = (
            by_verdict.get(strategy.get("readiness", NOT_READY), 0) + 1
        )
    active = len([s for s in strategies if not s.get("retired")])
    enabled_by_account: dict[str, int] = {}
    for link in links:
        if link.get("enabled"):
            enabled_by_account[link["account_key"]] = enabled_by_account.get(link["account_key"], 0) + 1

    lines += [
        "",
        "STRATEGIES",
        f"  {active} active  ·  Ready {by_verdict.get(READY, 0)}  ·  "
        f"Almost {by_verdict.get(ALMOST_READY, 0)}  ·  Not ready {by_verdict.get(NOT_READY, 0)}",
    ]
    for account in accounts:
        lines.append(f"  enabled on {account['key']}: {enabled_by_account.get(account['key'], 0)}")

    # --- changes today -----------------------------------------------------
    changed = [
        s for s in strategies
        if s.get("readiness_updated_at") and s["readiness_updated_at"] >= day_start_iso
    ]
    lines += ["", "CHANGES TODAY"]
    if changed:
        for strategy in changed:
            lines.append(
                f"  {strategy.get('display_name') or strategy['name']} → "
                f"{_LABEL.get(strategy.get('readiness'), strategy.get('readiness'))}"
            )
    else:
        lines.append("  none")

    # --- performance -------------------------------------------------------
    for account in accounts:
        closed = supabase.select(
            "trades",
            {
                "status": "eq.CLOSED",
                "account_key": f"eq.{account['key']}",
                "closed_at": f"gte.{day_start_iso}",
            },
        )
        net = sum(float(t["realized_pnl"]) for t in closed if t.get("realized_pnl") is not None)
        opened = supabase.select(
            "trades",
            {"account_key": f"eq.{account['key']}", "opened_at": f"gte.{day_start_iso}"},
        )
        label = account["account_type"].upper()
        lines += ["", f"{label}  ·  {account['key']}  (today)"]
        if not closed and not opened:
            lines.append("  no trades")
        else:
            lines.append(f"  {len(opened)} opened  ·  {len(closed)} closed  ·  net {_money(net)}")

    # --- warnings ----------------------------------------------------------
    if account_block:
        warnings.append(account_block)
    if by_verdict.get(READY, 0) == 0:
        warnings.append("no strategy is Ready - live trading would place no trades by design")

    lines += ["", "WARNINGS"]
    if warnings:
        lines += [f"  • {w}" for w in warnings]
    else:
        lines.append("  none")
    return "\n".join(lines)
