import { useCallback, useEffect, useState } from "react";
import { supabase } from "./supabase";
import type { Account, Readiness, Strategy, StrategyAccount, StrategyEvaluation, Trade } from "../types";

const POLL_MS = 30_000;

const RANK: Record<Readiness, number> = { ready: 2, almost_ready: 1, not_ready: 0 };

/** The READY bar, mirrored from engine/config.py Settings.readiness_*. These are
 * duplicated here ONLY to render progress visuals; the evaluator remains the
 * sole authority that grants readiness, and its verdict_reason stays the
 * authoritative text. Keep in sync with the engine - but note the bar changes
 * rarely and on purpose ("the bar is the product", docs/strategy-lab.md), so
 * drift is unlikely. If they ever diverge, the engine wins. */
export const READINESS = {
  minTradesReady: 100, // readiness_min_trades_ready
  minTradesAlmost: 30, // readiness_min_trades_almost - first point a verdict appears
  minProfitFactor: 1.2, // readiness_min_profit_factor
  maxDrawdownR: 15, // readiness_max_drawdown_r
} as const;

export type Gate = { key: string; label: string; met: boolean };

/** The four quality gates a strategy must clear to be READY, in the same order
 * engine/evaluator.py classify() applies them. The trade-count minimum is shown
 * separately (as a progress bar) because it is the one that actually moves;
 * these are the pass/fail checks. A null field reads as "not met yet" rather
 * than a false pass - an unproven strategy must never look proven. */
export function readinessGates(e: StrategyEvaluation | null): Gate[] {
  const n = e?.trades_count ?? 0;
  const exp = e?.expectancy_r ?? null;
  const ciLow = e?.ci_low ?? null;
  const pf = e?.profit_factor ?? null;
  const dd = e?.max_drawdown_r ?? null;
  return [
    { key: "sample", label: `${READINESS.minTradesReady}+ trades`, met: n >= READINESS.minTradesReady },
    { key: "expectancy", label: "Expectancy > 0", met: exp !== null && exp > 0 },
    { key: "ci", label: "95% CI clears zero", met: ciLow !== null && ciLow > 0 },
    {
      key: "pf",
      label: `Profit factor ≥ ${READINESS.minProfitFactor}`,
      met: pf !== null && pf >= READINESS.minProfitFactor,
    },
    {
      key: "drawdown",
      label: `Drawdown ≤ ${READINESS.maxDrawdownR}R`,
      met: dd !== null && dd <= READINESS.maxDrawdownR,
    },
  ];
}

/** Strategy-lab data: registries + the latest evaluation snapshot per
 * (strategy, account). Kept separate from useDashboardData so the lab can poll
 * on its own, slower cadence - evaluations only change every 30 min. */
export function useStrategyLab() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [links, setLinks] = useState<StrategyAccount[]>([]);
  const [evaluations, setEvaluations] = useState<StrategyEvaluation[]>([]);
  const [closedTrades, setClosedTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [acc, strat, link, evals, trades] = await Promise.all([
      supabase.from("accounts").select("*").order("account_type"),
      supabase.from("strategies").select("*").order("name"),
      supabase.from("strategy_accounts").select("*"),
      // Newest first; we reduce to the latest per (strategy, account) below.
      supabase
        .from("strategy_evaluations")
        .select("*")
        .order("computed_at", { ascending: false })
        .limit(500),
      // Newest-first, NOT oldest-first. The cap is global across all strategies
      // and both accounts, so `ascending: true` froze every equity curve on
      // ancient history the moment the lab passed `limit` total closed trades -
      // recent trades simply never made it into the fetched window. Descending
      // keeps the window on the most recent trades; rSeries flips each strategy's
      // slice back to chronological order for the curve. Trade-off: the curve is
      // the most recent <=limit trades per strategy, not all-time - fine for a
      // sparkline, and the evaluator still computes the authoritative stats from
      // the full history server-side.
      supabase
        .from("trades")
        .select("*")
        .eq("status", "CLOSED")
        .order("closed_at", { ascending: false })
        .limit(1000),
    ]);
    setAccounts(acc.data ?? []);
    setStrategies(strat.data ?? []);
    setLinks(link.data ?? []);
    setEvaluations(evals.data ?? []);
    setClosedTrades(trades.data ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  return { accounts, strategies, links, evaluations, closedTrades, loading, refresh };
}

/** Latest snapshot per (strategy, account). `evaluations` must be newest-first. */
export function latestEvaluation(
  evaluations: StrategyEvaluation[],
  strategyName: string,
  accountKey: string
): StrategyEvaluation | null {
  return (
    evaluations.find((e) => e.strategy_name === strategyName && e.account_key === accountKey) ?? null
  );
}

export function linkFor(
  links: StrategyAccount[],
  strategyName: string,
  accountKey: string
): StrategyAccount | null {
  return links.find((l) => l.strategy_name === strategyName && l.account_key === accountKey) ?? null;
}

/** Ranking: readiness first, then how strong the *proven* edge is (CI lower
 * bound - the honest measure, not the flattering point estimate), then sample
 * size as the tiebreak.
 *
 * Shared by the lab table and the stat tiles so "which strategy is leading" can
 * never mean two different things on one screen. */
export function rankStrategies(
  strategies: Strategy[],
  evaluations: StrategyEvaluation[],
  accountKey: string
): Strategy[] {
  const score = (s: Strategy): number[] => {
    const e = latestEvaluation(evaluations, s.name, accountKey);
    return [
      RANK[s.readiness] ?? 0,
      e?.ci_low ?? -99,
      e?.expectancy_r ?? -99,
      e?.trades_count ?? 0,
    ];
  };
  return [...strategies].sort((a, b) => {
    const sa = score(a);
    const sb = score(b);
    for (let i = 0; i < sa.length; i++) if (sb[i] !== sa[i]) return sb[i] - sa[i];
    return a.name.localeCompare(b.name);
  });
}

/** Realized R per closed trade, oldest first. Trades without a recorded
 * risk_amount predate risk capture and can't be expressed in R, so they're
 * skipped rather than guessed at. */
export function rSeries(trades: Trade[], strategyName: string, accountKey: string): number[] {
  return trades
    .filter(
      (t) =>
        t.strategy_name === strategyName &&
        t.account_key === accountKey &&
        t.realized_pnl !== null &&
        t.risk_amount !== null &&
        t.risk_amount !== 0
    )
    // The fetch is newest-first (global cap - see useStrategyLab), but a
    // cumulative equity curve must run oldest -> newest. filter() returns a
    // fresh array, so reversing it here is safe and doesn't touch the caller's.
    .reverse()
    .map((t) => (t.realized_pnl as number) / (t.risk_amount as number));
}

export async function setStrategyEnabled(id: number, enabled: boolean) {
  return supabase
    .from("strategy_accounts")
    .update({ enabled, updated_at: new Date().toISOString() })
    .eq("id", id);
}

export async function setLiveOverride(id: number, live_override: boolean) {
  return supabase
    .from("strategy_accounts")
    .update({ live_override, updated_at: new Date().toISOString() })
    .eq("id", id);
}
