"""Look for things that are WRONG with recorded trades - not things to tune.

This is deliberately not a parameter search. Tuning on the same data that
produced a verdict manufactures the false positive that gets funded (see the
standing rule in docs/research-log.md). Every check here asks whether a
strategy did what its code says, which cannot be gamed by outcome:

  1. INTEGRITY   - rows that cannot support a verdict at all (no risk_amount,
                   so no R; no signal_id, so no intent to compare against).
  2. INTENT      - the fill vs the price the signal asked for, in R. Systematic
                   adverse slippage is an execution defect, not a bad strategy.
  3. STOPS       - a stop-out should return exactly -1.000R. What sits below
                   that is spread, commission and slippage, measured with no
                   cost model in the way. Far below means the stop did not hold.
  4. COSTS       - gross vs net per trade from the broker's OWN commission and
                   swap figures, which separates "the signal is bad" from "the
                   toll is bigger than the edge".
  5. SHAPE       - is a big drawdown one broken stretch or the normal texture
                   of the strategy? Those need different responses.
  6. CLOCK       - trades opened while that engine's server-time offset was
                   wrong. Their bars were mislabelled, so they cannot be read
                   as evidence either way.

Read-only:

    python scripts/audit_trades.py
    python scripts/audit_trades.py --strategy range_fade_v1
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.supabase_client import SupabaseClient

# Days on which an engine's measured UTC offset was wrong, so the bars its
# strategies judged were mislabelled. Established by comparing each engine's
# evaluations against the other's; see docs/research-log.md.
CONTAMINATED = {
    "icmarkets-demo": {"2026-08-30", "2026-08-31", "2026-09-05", "2026-09-06",
                       "2026-09-07", "2026-09-08", "2026-09-09"},
    "icmarkets-live": {"2026-09-05", "2026-09-06", "2026-09-07"},
}

# A stop-out lands near -1R. Wider than this and it is a gap or a failed stop,
# not the ordinary cost of being stopped out.
STOP_BAND = (-1.6, -0.85)
PAGE = 1000


def fetch_all(supabase: SupabaseClient, table: str, params: dict) -> list[dict]:
    """PostgREST caps a select at 1000 rows; page past it rather than silently
    analysing the first page and calling it the population."""
    out: list[dict] = []
    while True:
        page = supabase.select(
            table, {**params, "limit": str(PAGE), "offset": str(len(out))}
        )
        out.extend(page)
        if len(page) < PAGE:
            return out


def realized_r(trade: dict) -> float | None:
    risk = trade.get("risk_amount")
    if not risk or trade.get("realized_pnl") is None:
        return None
    return trade["realized_pnl"] / risk


def integrity(trades: list[dict]) -> None:
    print("1. INTEGRITY - can these rows support a verdict at all?")
    per_strategy: dict[str, Counter] = defaultdict(Counter)
    for t in trades:
        c = per_strategy[t["strategy_name"]]
        c["closed"] += 1
        if not t.get("risk_amount"):
            c["no risk_amount (no R)"] += 1
        if t.get("signal_id") is None:
            c["no signal_id (no intent)"] += 1
        if t.get("initial_stop_loss") is None:
            c["no initial stop"] += 1
        if t.get("gross_profit") is None:
            c["no fee split"] += 1
    print(f"   {'strategy':24} {'closed':>7} {'no R':>6} {'no intent':>10} "
          f"{'no stop':>8} {'no fees':>8}")
    for name, c in sorted(per_strategy.items()):
        print(f"   {name:24} {c['closed']:>7} {c['no risk_amount (no R)']:>6} "
              f"{c['no signal_id (no intent)']:>10} {c['no initial stop']:>8} "
              f"{c['no fee split']:>8}")
    print()


def intent(supabase: SupabaseClient, trades: list[dict]) -> None:
    """Fill price vs the price the signal asked for, in R. Sign convention:
    positive = the fill was WORSE than intended, whichever way the trade went."""
    print("2. INTENT - did the fill match what the signal asked for?")
    ids = [t["signal_id"] for t in trades if t.get("signal_id")]
    if not ids:
        print("   no trades carry a signal_id\n")
        return

    signals: dict[int, dict] = {}
    for i in range(0, len(ids), 200):
        chunk = ",".join(str(x) for x in ids[i:i + 200])
        for s in supabase.select(
            "signals", {"id": f"in.({chunk})", "select": "id,entry_price,stop_loss", "limit": "300"}
        ):
            signals[s["id"]] = s

    per_strategy: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        s = signals.get(t.get("signal_id"))
        if not s or s.get("entry_price") is None or s.get("stop_loss") is None:
            continue
        intended_risk = abs(s["entry_price"] - s["stop_loss"])
        if intended_risk <= 0:
            continue
        drift = t["entry_price"] - s["entry_price"]
        if t["direction"].upper().startswith("S"):
            drift = -drift  # a lower fill is worse for a short
        per_strategy[t["strategy_name"]].append(drift / intended_risk)

    if not per_strategy:
        print("   no trade could be joined to its signal's intended prices\n")
        return
    print(f"   {'strategy':24} {'n':>5} {'median':>9} {'mean':>9} {'worst':>9}")
    for name, v in sorted(per_strategy.items()):
        print(f"   {name:24} {len(v):>5} {statistics.median(v):>+9.3f} "
              f"{statistics.fmean(v):>+9.3f} {max(v):>+9.3f}")
    print("   (R of intended risk given up at entry; + is adverse. Sustained")
    print("    values near or above the edge itself would be the whole story.)\n")


def stops(trades: list[dict]) -> None:
    print("3. STOPS - a stop-out should return exactly -1.000R")
    per_strategy: dict[str, list[float]] = defaultdict(list)
    overshoot: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        r = realized_r(t)
        if r is None:
            continue
        if STOP_BAND[0] <= r <= STOP_BAND[1]:
            per_strategy[t["strategy_name"]].append(-1.0 - r)  # + = cost paid
        elif r < STOP_BAND[0]:
            overshoot[t["strategy_name"]].append(r)
    print(f"   {'strategy':24} {'n':>5} {'median cost':>12} {'blew past stop':>15}")
    for name in sorted(set(per_strategy) | set(overshoot)):
        costs = per_strategy.get(name, [])
        blown = overshoot.get(name, [])
        cost_text = f"{statistics.median(costs):+.3f}R" if costs else "-"
        blown_text = f"{len(blown)}  (worst {min(blown):.2f}R)" if blown else "0"
        print(f"   {name:24} {len(costs):>5} {cost_text:>12} {blown_text:>15}")
    print()


def costs(trades: list[dict]) -> None:
    """Gross vs net from the broker's own numbers - no cost model involved."""
    print("4. COSTS - the broker's own commission and swap, per trade")
    per_strategy: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for t in trades:
        risk = t.get("risk_amount")
        if not risk or t.get("gross_profit") is None:
            continue
        fees = (t.get("commission") or 0.0) + (t.get("swap") or 0.0)
        per_strategy[t["strategy_name"]].append((t["gross_profit"] / risk, fees / risk))
    if not per_strategy:
        print("   no trade carries the fee split yet (migration 0015 is recent)\n")
        return
    print(f"   {'strategy':24} {'n':>5} {'gross/trade':>12} {'fees/trade':>11} {'net':>9}")
    for name, rows in sorted(per_strategy.items()):
        gross = statistics.fmean(r for r, _ in rows)
        fee = statistics.fmean(f for _, f in rows)
        print(f"   {name:24} {len(rows):>5} {gross:>+12.3f} {fee:>+11.3f} {gross + fee:>+9.3f}")
    print()


def shape(trades: list[dict], strategy: str) -> None:
    """Is a large drawdown one broken stretch, or the strategy's normal texture?"""
    closed = sorted(
        (t for t in trades if t["strategy_name"] == strategy and realized_r(t) is not None),
        key=lambda t: t["closed_at"] or t["opened_at"],
    )
    if not closed:
        return
    print(f"5. SHAPE - {strategy}'s equity curve in R")
    equity = peak = 0.0
    worst = 0.0
    worst_at = ("", "")
    run_start = closed[0]["closed_at"]
    for t in closed:
        equity += realized_r(t)
        if equity > peak:
            peak, run_start = equity, t["closed_at"]
        if peak - equity > worst:
            worst = peak - equity
            worst_at = (run_start, t["closed_at"])
    losses = [realized_r(t) for t in closed if realized_r(t) < 0]
    print(f"   {len(closed)} closed, total {equity:+.1f}R, max drawdown {worst:.1f}R")
    if worst_at[0]:
        print(f"   deepest stretch: {worst_at[0][:10]} -> {worst_at[1][:10]}")
    print(f"   {len(losses)} losers, median {statistics.median(losses):+.2f}R, "
          f"worst {min(losses):+.2f}R")
    print()


def clock(trades: list[dict]) -> None:
    print("6. CLOCK - trades opened while that engine's bars were mislabelled")
    flagged: dict[str, Counter] = defaultdict(Counter)
    for t in trades:
        day = (t["opened_at"] or "")[:10]
        if day in CONTAMINATED.get(t["account_key"], ()):
            flagged[t["strategy_name"]][t["account_key"]] += 1
    if not flagged:
        print("   none\n")
        return
    for name, accounts in sorted(flagged.items()):
        for account, n in accounts.items():
            total = sum(1 for t in trades if t["strategy_name"] == name
                        and t["account_key"] == account)
            print(f"   {name:24} {account:16} {n:>4} of {total} suspect")
    print("   Exclude these from any verdict: the bars they judged were not the")
    print("   bars they were labelled as, so they are evidence of nothing.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit recorded trades for defects.")
    parser.add_argument("--strategy", default="range_fade_v1", help="strategy for the shape report")
    args = parser.parse_args()

    supabase = SupabaseClient(Settings())
    trades = fetch_all(supabase, "trades", {
        "status": "eq.CLOSED",
        "select": "strategy_name,account_key,symbol,direction,entry_price,stop_loss,"
                  "initial_stop_loss,risk_amount,realized_pnl,gross_profit,commission,"
                  "swap,signal_id,opened_at,closed_at",
        "order": "opened_at.asc",
    })
    print(f"{len(trades)} closed trades  ·  {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n"
          .replace("·", "-"))

    integrity(trades)
    intent(supabase, trades)
    stops(trades)
    costs(trades)
    shape(trades, args.strategy)
    clock(trades)


if __name__ == "__main__":
    main()
