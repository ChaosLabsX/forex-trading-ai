import { useCallback, useEffect, useState } from "react";
import { supabase } from "./supabase";
import type { Heartbeat, Signal, Trade } from "../types";

const POLL_MS = 15_000;

/** Single polling loop for everything the dashboard shows - one interval,
 * one refresh cycle, instead of every component running its own timer. */
export function useDashboardData() {
  const [heartbeat, setHeartbeat] = useState<Heartbeat | null>(null);
  const [openTrades, setOpenTrades] = useState<Trade[]>([]);
  const [closedTrades, setClosedTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const [hb, open, closed, sigs] = await Promise.all([
      supabase
        .from("engine_heartbeats")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
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
    setHeartbeat(hb.data ?? null);
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

  return { heartbeat, openTrades, closedTrades, signals, loading, updatedAt, refresh };
}
