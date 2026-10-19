r"""Why trades win and lose, from how they ended and how far they went (0017).

    .venv\Scripts\python.exe scripts\trade_autopsy_report.py                 # every strategy, both accounts
    .venv\Scripts\python.exe scripts\trade_autopsy_report.py london_breakout_v1

Reads Supabase only (no MT5), so it runs anywhere the .env is. Small: one
select of the columns it needs.

Every pattern this prints is a HYPOTHESIS. The way to use one is to write it
down as a single rule decided in advance, test it once in scripts/backtest.py
over years of history, and keep it only if it clearly holds there. Changing a
live rule because of what the last few losers had in common is how a fake edge
gets funded - see docs/research-log.md.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings                     # noqa: E402
from engine.supabase_client import SupabaseClient     # noqa: E402

MIN_FOR_PATTERN = 20  # fewer trades than this in a group: shown, but flagged as anecdote


def bucket(value: float, edges: list[tuple[float, str]]) -> str:
    for upper, label in edges:
        if value < upper:
            return label
    return edges[-1][1]


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:3.0f}%" if total else "  -"


def report(name: str, account: str, trades: list[dict]) -> None:
    rs = [t["r"] for t in trades]
    print(f"\n{'=' * 72}\n{name} | {account} | {len(trades)} closed trades, "
          f"{statistics.mean(rs):+.3f}R per trade")
    if len(trades) < MIN_FOR_PATTERN:
        print(f"  (under {MIN_FOR_PATTERN} trades - read everything below as anecdote, not pattern)")

    print("\n  How they ended:")
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t["exit_reason"] or "not recorded"].append(t["r"])
    for reason, group in sorted(by_exit.items(), key=lambda kv: -len(kv[1])):
        print(f"    {reason:15s} {len(group):4d}  {pct(len(group), len(trades))}   avg {statistics.mean(group):+.2f}R")

    measured = [t for t in trades if t["mfe"] is not None]
    if not measured:
        print("\n  No excursions recorded yet - run scripts/backfill_trade_autopsy.py on the VPS.")
        return

    losses = [t for t in measured if t["exit_reason"] == "stop"]
    if losses:
        print(f"\n  Full-stop losses ({len(losses)}): how far they went IN our favour first")
        edges = [(0.1, "never really (<0.1R)"), (0.5, "a little (0.1-0.5R)"), (1.0, "close (0.5-1.0R)"),
                 (99, "past +1R (stop not moved?)")]
        counts = defaultdict(int)
        for t in losses:
            counts[bucket(t["mfe"], edges)] += 1
        for _, label in edges:
            if counts[label]:
                print(f"    {label:28s} {counts[label]:4d}  {pct(counts[label], len(losses))}")
        print("    -> mostly 'never': the ENTRY is the weak point. Mostly 'close': the EXIT is.")

    wins = [t for t in measured if t["exit_reason"] == "target"]
    if wins:
        print(f"\n  Winners ({len(wins)}): how far they went AGAINST us before winning")
        edges = [(-0.75, "nearly stopped (< -0.75R)"), (-0.5, "deep (-0.75 to -0.5R)"),
                 (-0.25, "some (-0.5 to -0.25R)"), (1, "barely (> -0.25R)")]
        counts = defaultdict(int)
        for t in wins:
            counts[bucket(t["mae"], edges)] += 1
        for _, label in edges:
            if counts[label]:
                print(f"    {label:28s} {counts[label]:4d}  {pct(counts[label], len(wins))}")

    scratches = [t for t in measured if t["exit_reason"] == "breakeven"]
    if scratches:
        best = [t["mfe"] for t in scratches]
        print(f"\n  Stopped at entry ({len(scratches)}): best point reached, median {statistics.median(best):+.2f}R, "
              f"max {max(best):+.2f}R")

    print("\n  By pair:")
    by_pair = defaultdict(list)
    for t in trades:
        by_pair[t["symbol"]].append(t)
    for symbol, group in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        rs_ = [t["r"] for t in group]
        costs = [t["cost_r"] for t in group if t["cost_r"] is not None]
        cost_text = f"  fees {statistics.mean(costs):.2f}R/trade" if costs else ""
        print(f"    {symbol:8s} {len(group):3d}  avg {statistics.mean(rs_):+.2f}R  total {sum(rs_):+5.1f}R{cost_text}")


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    supabase = SupabaseClient(Settings())
    try:
        rows = supabase.select("trades", {
            "status": "eq.CLOSED",
            "void_reason": "is.null",
            "select": "account_key,strategy_name,symbol,realized_pnl,risk_amount,commission,swap,"
                      "exit_reason,max_favorable_r,max_adverse_r",
            "order": "closed_at.asc",
            "limit": "10000",
        })
    except Exception as exc:
        if "exit_reason" in str(exc) or "max_favorable_r" in str(exc):
            print("The autopsy columns don't exist yet - run supabase/migrations/0017_trade_autopsy.sql first.")
            return 2
        raise
    groups = defaultdict(list)
    for r in rows:
        if r["realized_pnl"] is None or not r["risk_amount"]:
            continue
        if only and r["strategy_name"] != only:
            continue
        fees = (r["commission"] or 0) + (r["swap"] or 0) if r["commission"] is not None else None
        groups[(r["strategy_name"], r["account_key"])].append({
            "symbol": r["symbol"],
            "r": r["realized_pnl"] / r["risk_amount"],
            "cost_r": -fees / r["risk_amount"] if fees is not None else None,
            "exit_reason": r["exit_reason"],
            "mfe": r["max_favorable_r"],
            "mae": r["max_adverse_r"],
        })
    if not groups:
        print("no closed trades" + (f" for {only}" if only else ""))
        return 1
    for (name, account), trades in sorted(groups.items()):
        report(name, account, trades)
    print("\nEvery pattern above is a hypothesis: one rule, decided in advance, tested once in "
          "scripts/backtest.py - never a live change on its own.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
