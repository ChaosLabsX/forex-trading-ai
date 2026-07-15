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


def money(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"


def price(value: float | None, like: float | None = None) -> str:
    """Format a price at the instrument's conventional precision.

    ATR arithmetic yields raw floats, so an unrounded stop reads
    `0.8086272890512113` - 16 digits of noise in a glanceable alert.

    Precision comes from the price's MAGNITUDE, not from the float's repr.
    repr() drops trailing zeros, so an entry of 1.34700 prints as "1.347" and a
    stop would silently render 3 digits while its neighbour rendered 5 - the kind
    of inconsistency that makes a reader doubt every other number. Magnitude
    matches FX convention across this whole universe: EURUSD 1.14 -> 5, USDJPY
    162 -> 3, XAUUSD 3300 -> 2, BTCUSD -> 2."""
    if value is None:
        return "-"
    reference = abs(like if like is not None else value)
    if reference < 10:
        digits = 5
    elif reference < 1000:
        digits = 3
    else:
        digits = 2
    return f"{value:.{digits}f}"


def _money(value: float) -> str:  # kept for existing callers
    return money(value)


# --- the message grammar ----------------------------------------------------
#
# Every alert has the same three-line shape, so the eye always finds the same
# thing in the same place:
#
#   <icon> HEADLINE · the number that matters
#   context (strategy · account)
#   detail, one line, only if it earns its place
#
# No event-type tag: "[trade_closed] ✅ WIN" says WIN twice. The icon and the
# headline are the tag.


def _line(icon: str, headline: str, context: str = "", detail: str = "") -> str:
    out = [f"{icon} {headline}"]
    if context:
        out.append(context)
    if detail:
        out.append(detail)
    return "\n".join(out)


def trade_opened(position, strategy: str, account: str, risk_amount: float | None) -> str:
    bits = [f"{position.lot_size} lot @ {price(position.entry_price, position.entry_price)}"]
    if risk_amount:
        bits.append(f"risk {money(-risk_amount)}")
    detail = "  ·  ".join(bits)
    if position.stop_loss is not None and position.take_profit is not None:
        detail += (
            f"\nSL {price(position.stop_loss, position.entry_price)}"
            f"  ·  TP {price(position.take_profit, position.entry_price)}"
        )
    return _line(
        "🟢",
        f"OPEN  ·  {position.symbol} {position.direction.value}",
        f"{strategy}  ·  {account}",
        detail,
    )


def trade_closed(symbol: str, direction, breakdown, strategy: str, account: str) -> str:
    """A win reports gross profit before fees; a loss reports the all-in figure.
    Win/loss is decided by the NET result, so a small gain eaten by commission
    correctly reads as a loss."""
    subject = f"{symbol} {direction}" if direction else symbol
    if breakdown is None:
        return _line(
            "⚪", f"CLOSED  ·  {subject}", f"{strategy}  ·  {account}", "result unavailable"
        )
    if breakdown.net >= 0:
        detail = "before fees"
        if abs(breakdown.fees) >= 0.005:
            detail += f"  ·  fees {money(breakdown.fees)}"
        return _line(
            "✅",
            f"WIN  ·  {subject}  ·  {money(breakdown.gross_profit)}",
            f"{strategy}  ·  {account}",
            detail,
        )
    return _line(
        "🔴",
        f"LOSS  ·  {subject}  ·  {money(breakdown.net)}",
        f"{strategy}  ·  {account}",
        "incl. fees",
    )


def stop_protected(position, strategy: str, account: str) -> str:
    """Sent ONCE per trade, the moment its stop reaches entry.

    That instant is the only one worth pushing: the trade can no longer lose.
    Every later trailing step is real but incremental - a runner to +3R fired
    four near-identical alerts, none of them actionable. Those are logged
    instead. And the strategy name is here because two strategies can now hold
    the same symbol independently, so "GBPUSD" alone is ambiguous."""
    return _line(
        "🛡",
        f"RISK-FREE  ·  {position.symbol} {position.direction.value}",
        f"{strategy}  ·  {account}",
        f"stop at entry {price(position.stop_loss, position.entry_price)}  ·  can no longer lose",
    )


def engine_event(icon: str, headline: str, account: str, detail: str = "") -> str:
    return _line(icon, headline, account, detail)


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
    icon = "🏆" if evaluation.verdict == READY else ("⬆️" if promoted else "⚠️")
    headline = _LABEL.get(evaluation.verdict, evaluation.verdict)

    lines = [
        f"{icon} {headline}  ·  {name}",
        # Not lowercased: READY is capitalised in _LABEL because it is the state
        # that matters, and "was ready" whispers the very thing a demotion alert
        # exists to shout.
        f"was {_LABEL.get(previous or NOT_READY, previous)}",
        stats_line(evaluation.stats),
        evaluation.reason,
    ]
    if evaluation.verdict == READY:
        lines.append("→ eligible for live once you enable it")
    elif previous == READY:
        lines.append("→ live trading stops unless you override")
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
