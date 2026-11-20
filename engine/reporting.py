"""Human-facing Telegram copy: trade and strategy events, and market hours.

Kept apart from the evaluator/loop so the wording can change without touching
any decision logic, and so every message can be unit-tested without a broker,
a database, or a network.
"""

from __future__ import annotations

import logging

from engine.evaluator import ALMOST_READY, NOT_READY, READY, Evaluation
from engine.stats import TradeStats

logger = logging.getLogger("engine.reporting")

_RANK = {NOT_READY: 0, ALMOST_READY: 1, READY: 2}
_LABEL = {NOT_READY: "Not ready", ALMOST_READY: "Almost ready", READY: "READY"}


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


def trade_untracked(position, strategy: str, account: str) -> str:
    """The position exists at the broker; the database never heard about it.

    Sent straight after the normal OPEN alert, because that alert has already
    told the user the trade is being handled and this is the correction. The
    detail is deliberately precise about what still protects the position and
    what does not: the broker's own SL/TP are set and will still fire, so this
    is not "unprotected money" - but nothing on this side will record the
    outcome, and reconciliation only ever looks at tickets it has a row for.
    """
    return _line(
        "⚠️",
        f"NOT RECORDED  ·  {position.symbol} {position.direction.value}",
        f"{strategy}  ·  {account}",
        f"ticket {position.id} is OPEN at the broker but could not be saved to the database.\n"
        "Its SL/TP still apply. The engine will not record its result, and it will not "
        "appear in the dashboard or the strategy's record - save or close it by hand.",
    )


def trade_closed(symbol: str, direction, breakdown, strategy: str, account: str,
                 exit_note: str | None = None) -> str:
    """Win or loss, the headline is the NET result - what reached the account,
    after fees. Until 2026-11-19 a win showed its gross, "before fees"; the
    owner asked for the real figure, and on this account commission is ~8% of
    each trade's risk, so the gross flattered every win. A win's detail line
    still names the fees, so the gross is one addition away. Win/loss is
    decided by the net, so a small gain eaten by commission reads as a loss.
    `exit_note` says how it ended (trade_autopsy.describe): "full stop, best
    was +0.6R" turns a bare loss into something you can learn from at a
    glance."""
    subject = f"{symbol} {direction}" if direction else symbol
    if breakdown is None:
        return _line(
            "⚪", f"CLOSED  ·  {subject}", f"{strategy}  ·  {account}", "result unavailable"
        )
    if breakdown.net >= 0:
        detail = "after fees"
        if abs(breakdown.fees) >= 0.005:
            detail += f"  ·  fees {money(breakdown.fees)}"
        if exit_note:
            detail += f"  ·  {exit_note}"
        return _line(
            "✅",
            f"WIN  ·  {subject}  ·  {money(breakdown.net)}",
            f"{strategy}  ·  {account}",
            detail,
        )
    return _line(
        "🔴",
        f"LOSS  ·  {subject}  ·  {money(breakdown.net)}",
        f"{strategy}  ·  {account}",
        f"incl. fees  ·  {exit_note}" if exit_note else "incl. fees",
    )


def execution_failed(signal, strategy: str, account: str, reason: str) -> str:
    """An order the risk engine approved and the broker then refused.

    The reason goes on the FACE of the alert. "order placement failed, see
    logs" is not a report, it is a homework assignment: it cost a multi-step
    dig through retcodes and symbol specs to learn that MidDE50's minimum stop
    distance exceeds its ATR stop. These are not all equal - "market closed"
    or "requote" are noise to ignore, while "not enough money" or "trading is
    disabled" want you now, and "invalid stops"/"invalid volume" usually mean
    the instrument is structurally untradeable (see docs/research-log.md). The
    reader can only tell those apart if the reason is here, so it is."""
    return _line(
        "⚠️",
        f"ORDER REJECTED  ·  {signal.symbol} {signal.direction.value}",
        f"{strategy}  ·  {account}",
        reason,
    )


def stop_protected(position, strategy: str, account: str) -> str:
    """Sent ONCE per trade, the moment its stop reaches entry.

    That instant is the only one worth pushing: from here the trade can't lose
    on price. It can still close slightly negative - the broker's commission is
    charged on every trade, win or lose, so a stop-out at entry nets minus the
    fees (a 0.03-lot CHFJPY scratch on 2026-10-12: $0.00 on price, -$0.22 in
    commission). This said "RISK-FREE ... can no longer lose" until then, which
    promised more than a stop at entry delivers. Every later trailing step is real but incremental - a runner to +3R fired
    four near-identical alerts, none of them actionable. Those are logged
    instead. And the strategy name is here because two strategies can now hold
    the same symbol independently, so "GBPUSD" alone is ambiguous."""
    return _line(
        "🛡",
        f"BREAKEVEN  ·  {position.symbol} {position.direction.value}",
        f"{strategy}  ·  {account}",
        f"stop at entry {price(position.stop_loss, position.entry_price)}  ·  worst case now: just the fees",
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


# --- market hours -------------------------------------------------------------
#
# Sent by the live engine when the FX week ends and begins (engine/loop.py,
# engine/market_hours.py). Times are Jakarta time, 12-hour, no year - the
# owner's own clock. The close carries the live account's week, pair by pair,
# best first: the one message that lists more than one detail line, because
# the owner asked for exactly that breakdown.


def market_opened(closes_at: str) -> str:
    return _line("🔓", f"MARKET OPEN  ·  closes {closes_at}")


def market_closed(opens_at: str, week_trades: list[dict]) -> str:
    """`week_trades`: the live account's trades closed this week, each with
    `symbol` and `realized_pnl` (net, after fees)."""
    scored = [t for t in week_trades if t.get("realized_pnl") is not None]
    head = f"🔒 MARKET CLOSED  ·  opens {opens_at}"
    if not scored:
        return f"{head}\nThis week: no trades"
    by_pair: dict[str, list[float]] = {}
    for t in scored:
        by_pair.setdefault(t["symbol"], []).append(float(t["realized_pnl"]))
    total = sum(sum(v) for v in by_pair.values())
    lines = [head, f"This week: {len(scored)} trade{'s' if len(scored) != 1 else ''}  ·  net {money(total)}"]
    for symbol, pnls in sorted(by_pair.items(), key=lambda kv: -sum(kv[1])):
        lines.append(f"{symbol}  {len(pnls)}  ·  {money(sum(pnls))}")
    return "\n".join(lines)
