import { useCallback, useEffect, useState } from "react";
import { supabase } from "./supabase";
import type { Account, Heartbeat, Signal, Trade } from "../types";

const POLL_MS = 15_000;
export const STALE_AFTER_MS = 3 * 60 * 1000; // heartbeats are sent every 60s

/** Per-account engine state. Derived here, once, so no component re-invents the
 * staleness or paused rule (they drifted apart the first time we tried). */
export type AccountHealth = {
  account: Account;
  heartbeat: Heartbeat | null;
  online: boolean;
  paused: boolean;
};

function healthFor(account: Account, beats: Heartbeat[]): AccountHealth {
  // beats arrive newest-first, so the first match per account IS the latest
  const heartbeat = beats.find((b) => b.account_key === account.key) ?? null;
  const online = heartbeat
    ? Date.now() - new Date(heartbeat.created_at).getTime() <= STALE_AFTER_MS
    : false;
  return {
    account,
    heartbeat,
    online,
    // A stale heartbeat says nothing about the engine's current pause state.
    paused: online && heartbeat?.status === "paused",
  };
}

/** Single polling loop for everything the dashboard shows - one interval,
 * one refresh cycle, instead of every component running its own timer. */
export function useDashboardData() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [health, setHealth] = useState<AccountHealth[]>([]);
  const [openTrades, setOpenTrades] = useState<Trade[]>([]);
  const [closedTrades, setClosedTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const [acc, beats, open, closed, sigs] = await Promise.all([
      supabase.from("accounts").select("*").order("account_type"),
      // Enough rows to cover the latest beat of every account (each beats once
      // per 60s), then reduced to one per account below.
      supabase
        .from("engine_heartbeats")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(100),
      supabase
        .from("trades")
        .select("*")
        .eq("status", "OPEN")
        .order("opened_at", { ascending: false }),
      supabase
        .from("trades")
        .select("*")
        .eq("status", "CLOSED")
        .order("closed_at", { ascending: false })
        .limit(50),
      supabase
        .from("signals")
        .select("*, ai_reviews(approved, confidence, rationale)")
        .order("created_at", { ascending: false })
        .limit(30),
    ]);
    const accountRows = acc.data ?? [];
    setAccounts(accountRows);
    setHealth(accountRows.map((a) => healthFor(a, beats.data ?? [])));
    setOpenTrades(open.data ?? []);
    setClosedTrades(closed.data ?? []);
    setSignals(sigs.data ?? []);
    setLoading(false);
    setUpdatedAt(new Date());
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  return { accounts, health, openTrades, closedTrades, signals, loading, updatedAt, refresh };
}
