import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "./supabase";
import type { Trade } from "../types";

/** Slower than the 15s dashboard loop on purpose: this is a settled-history
 * figure, and a closed trade never changes again. */
const POLL_MS = 60_000;
const PAGE = 1000;

export type PeriodMode = "month" | "year" | "custom" | "all";

export type Period = {
  mode: PeriodMode;
  /** Anchor for month/year stepping. Ignored by custom/all. */
  anchor: Date;
  /** yyyy-mm-dd, custom mode only. */
  from: string;
  to: string;
};

/** What the panel renders. Every field is derived from the SAME trade list, so
 * the headline and the breakdown beneath it cannot disagree. */
export type PnlSummary = {
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  winRate: number | null;
  /** Sum of realized_pnl - the true change to the account, always. */
  net: number;
  /** Sum of gross_profit. NULL when any trade in the period predates
   * migration 0015, because a partial sum would silently understate. */
  gross: number | null;
  /** commission + swap, summed. NULL under the same condition as `gross`. */
  fees: number | null;
  /** How many trades in the period carry no fee split. */
  missingBreakdown: number;
  /** Closed with no P&L at all - MT5 never returned one. Excluded from the
   * sums, surfaced so a total is never quietly incomplete. */
  unknownPnl: number;
  best: number | null;
  worst: number | null;
  first: string | null;
  last: string | null;
};

export function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function startOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 0, 1);
}

/** Half-open [start, end) in LOCAL time - the user reads "September" as their
 * own September, not UTC's. `null` start/end means unbounded. */
export function periodBounds(p: Period): { start: Date | null; end: Date | null } {
  if (p.mode === "all") return { start: null, end: null };
  if (p.mode === "month") {
    const start = startOfMonth(p.anchor);
    return { start, end: new Date(start.getFullYear(), start.getMonth() + 1, 1) };
  }
  if (p.mode === "year") {
    const start = startOfYear(p.anchor);
    return { start, end: new Date(start.getFullYear() + 1, 0, 1) };
  }
  // Custom: both ends inclusive of the whole day the user typed, which is what
  // "to: 30 September" means to a person. An unset end means "up to now".
  const start = p.from ? new Date(`${p.from}T00:00:00`) : null;
  const end = p.to ? new Date(`${p.to}T00:00:00`) : null;
  if (end) end.setDate(end.getDate() + 1);
  return { start, end };
}

export function inPeriod(iso: string, p: Period): boolean {
  const { start, end } = periodBounds(p);
  const t = new Date(iso).getTime();
  if (start && t < start.getTime()) return false;
  if (end && t >= end.getTime()) return false;
  return true;
}

export function summarize(trades: Trade[]): PnlSummary {
  // A closed trade with no realized_pnl is not a zero - MT5 never told us the
  // result. Counting it as 0 would put a fake breakeven in the total.
  const scored = trades.filter((t) => t.realized_pnl !== null);
  const unknownPnl = trades.length - scored.length;

  // `?? null`, not `=== null`: until migration 0015 is applied the column does
  // not exist, so PostgREST omits it and the field arrives `undefined`. Reading
  // that as a known zero would put NaN in a money figure.
  const hasSplit = (t: Trade) => (t.gross_profit ?? null) !== null;
  const missingBreakdown = scored.filter((t) => !hasSplit(t)).length;
  const feesKnown = missingBreakdown === 0 && scored.length > 0;

  let net = 0;
  let gross = 0;
  let fees = 0;
  let wins = 0;
  let losses = 0;
  let breakeven = 0;
  let best: number | null = null;
  let worst: number | null = null;

  for (const t of scored) {
    const pnl = t.realized_pnl as number;
    net += pnl;
    if (feesKnown) {
      gross += t.gross_profit ?? 0;
      fees += (t.commission ?? 0) + (t.swap ?? 0);
    }
    // Win/loss is decided by the NET result, matching engine/reporting.py: a
    // gain that commission ate is a loss, however the gross reads.
    if (pnl > 0) wins++;
    else if (pnl < 0) losses++;
    else breakeven++;
    if (best === null || pnl > best) best = pnl;
    if (worst === null || pnl < worst) worst = pnl;
  }

  const decided = wins + losses;
  const times = scored
    .map((t) => t.closed_at)
    .filter((c): c is string => c !== null)
    .sort();

  return {
    trades: scored.length,
    wins,
    losses,
    breakeven,
    winRate: decided > 0 ? wins / decided : null,
    net,
    gross: feesKnown ? gross : null,
    fees: feesKnown ? fees : null,
    missingBreakdown,
    unknownPnl,
    best,
    worst,
    first: times[0] ?? null,
    last: times[times.length - 1] ?? null,
  };
}

/** The number to put in lights, under the house convention (same rule as the
 * Telegram grammar in engine/reporting.py): a win is reported BEFORE fees, a
 * loss is reported ALL-IN. Which of the two it is, is decided by the net -
 * never by the gross - so costs can turn a nominal gain into a loss.
 *
 * Falls back to net whenever the fee split is unavailable, because showing a
 * net figure under a "before fees" label would be simply wrong. */
export function headline(s: PnlSummary): { value: number; basis: "gross" | "net" } {
  if (s.net >= 0 && s.gross !== null) return { value: s.gross, basis: "gross" };
  return { value: s.net, basis: "net" };
}

/** Every CLOSED trade for one account. Separate from useDashboardData, which
 * caps closed trades at 50 for the recent-history table - an all-time total
 * built on a capped list would silently stop growing. */
export function useAccountTrades(accountKey: string | null) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!accountKey) {
      setTrades([]);
      setLoading(false);
      return;
    }
    const all: Trade[] = [];
    for (let from = 0; ; from += PAGE) {
      // "*" rather than a column list: supabase-js infers the row type from the
      // select string as a literal, so a concatenated list types as an error
      // array instead of Trade[]. The extra columns are a handful of bytes.
      const { data, error } = await supabase
        .from("trades")
        .select("*")
        .eq("account_key", accountKey)
        .eq("status", "CLOSED")
        .order("closed_at", { ascending: false })
        .range(from, from + PAGE - 1);
      if (error || !data) break;
      all.push(...(data as Trade[]));
      if (data.length < PAGE) break;
    }
    // A voided trade is excluded from every statistic by definition (0013), and
    // that has to include the money total or the panel and the lab disagree.
    setTrades(all.filter((t) => t.void_reason === null));
    setLoading(false);
  }, [accountKey]);

  useEffect(() => {
    setLoading(true);
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { trades, loading, refresh };
}

/** The months/years that actually contain trades, so the arrows can stop at
 * the edges of real history instead of walking into empty decades. */
export function useHistoryRange(trades: Trade[]) {
  return useMemo(() => {
    const times = trades
      .map((t) => t.closed_at)
      .filter((c): c is string => c !== null)
      .map((c) => new Date(c).getTime());
    if (times.length === 0) return { earliest: null as Date | null, latest: null as Date | null };
    return { earliest: new Date(Math.min(...times)), latest: new Date(Math.max(...times)) };
  }, [trades]);
}
