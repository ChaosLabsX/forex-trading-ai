import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import type { Heartbeat } from "../types";

const STALE_AFTER_MS = 3 * 60 * 1000; // heartbeats are sent every 60s

export function EngineHealth() {
  const [heartbeat, setHeartbeat] = useState<Heartbeat | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const { data } = await supabase
        .from("engine_heartbeats")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (!cancelled) {
        setHeartbeat(data);
        setLoading(false);
      }
    }

    load();
    const interval = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (loading) return <div className="card">Loading engine health...</div>;

  if (!heartbeat) {
    return (
      <div className="card status-bad">
        <h2>Engine Health</h2>
        <p>No heartbeat received yet - is the engine running?</p>
      </div>
    );
  }

  const ageMs = Date.now() - new Date(heartbeat.created_at).getTime();
  const isStale = ageMs > STALE_AFTER_MS;
  const statusClass = isStale ? "status-bad" : heartbeat.broker_connected ? "status-good" : "status-warn";

  return (
    <div className={`card ${statusClass}`}>
      <h2>Engine Health</h2>
      <p>
        <strong>{isStale ? "STALE" : "LIVE"}</strong> - last heartbeat{" "}
        {new Date(heartbeat.created_at).toLocaleString()}
      </p>
      <p>Broker connected: {heartbeat.broker_connected ? "yes" : "no"}</p>
    </div>
  );
}
