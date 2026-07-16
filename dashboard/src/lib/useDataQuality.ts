import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "./supabase";
import type { Account } from "../types";

const POLL_MS = 60_000;

/** Per-account counts of closed trades the evaluator silently excludes from
 * every statistic. Each category maps to a real, previously-lived incident:
 *
 *   - voided: a manual repair marked the row untrustworthy (migration 0013 -
 *     the cross-account reconcile bug that closed 43 demo trades with no P&L
 *     while an orphaned live engine ran unnoticed).
 *   - unknownPnl: reconciliation marked the trade CLOSED but MT5 never
 *     returned a P&L for it. Permanent - there is no retry once a trade
 *     leaves the OPEN set (see EngineLoop._reconcile_closed_trades).
 *   - missingRisk: the trade has real P&L but no captured risk_amount, so it
 *     is invisible to trades_count/expectancy/CI/profit-factor even though it
 *     still contributes to the raw dollar total shown elsewhere.
 *
 * A dead lab and a lab quietly excluding everything it "collects" look
 * identical from the tiles alone - this exists so that difference is never
 * invisible again. */
export type DataQualityRow = {
  accountKey: string;
  accountLabel: string;
  closedTotal: number;
  voided: number;
  unknownPnl: number;
  missingRisk: number;
};

function countOf(result: { count: number | null; error: { message: string } | null }): number {
  if (result.error) throw new Error(result.error.message);
  return result.count ?? 0;
}

async function fetchOne(account: Account): Promise<DataQualityRow> {
  const key = account.key;

  const [closedTotalRes, voidedRes, unknownPnlRes, missingRiskRes] = await Promise.all([
    supabase.from("trades").select("*", { count: "exact", head: true })
      .eq("account_key", key).eq("status", "CLOSED"),
    supabase.from("trades").select("*", { count: "exact", head: true })
      .eq("account_key", key).not("void_reason", "is", null),
    supabase.from("trades").select("*", { count: "exact", head: true })
      .eq("account_key", key).eq("status", "CLOSED")
      .is("realized_pnl", null).is("void_reason", null),
    supabase.from("trades").select("*", { count: "exact", head: true })
      .eq("account_key", key).eq("status", "CLOSED")
      .not("realized_pnl", "is", null).is("risk_amount", null).is("void_reason", null),
  ]);

  return {
    accountKey: key,
    accountLabel: account.label,
    closedTotal: countOf(closedTotalRes),
    voided: countOf(voidedRes),
    unknownPnl: countOf(unknownPnlRes),
    missingRisk: countOf(missingRiskRes),
  };
}

/** Own slow poll, independent of useDashboardData/useStrategyLab - this is a
 * health check, not trading data, so it doesn't need their cadence and
 * shouldn't add load to it. Re-reads `accounts` via a ref rather than
 * restarting the interval on every reference change (useStrategyLab's own
 * poll gives `accounts` a new array identity every 30s even when unchanged). */
export function useDataQuality(accounts: Account[]) {
  const [rows, setRows] = useState<DataQualityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const accountsRef = useRef(accounts);
  accountsRef.current = accounts;

  const refresh = useCallback(async () => {
    const current = accountsRef.current;
    if (current.length === 0) return;
    try {
      const results = await Promise.all(current.map(fetchOne));
      setRows(results);
    } catch {
      // A failed health check must not read as "all clear" - leave the last
      // known rows in place rather than clearing them to zero.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, accounts.length]);

  return { rows, loading };
}
