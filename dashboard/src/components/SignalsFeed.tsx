import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import type { Signal } from "../types";

export function SignalsFeed() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const { data } = await supabase
        .from("signals")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(30);
      if (!cancelled) {
        setSignals(data ?? []);
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

  return (
    <div className="card">
      <h2>Recent Signals</h2>
      {loading ? (
        <p>Loading...</p>
      ) : signals.length === 0 ? (
        <p className="muted">No signals logged yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Fired</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id}>
                <td>{new Date(s.created_at).toLocaleString()}</td>
                <td>{s.symbol}</td>
                <td>{s.strategy_name}</td>
                <td className={s.fired ? "long" : "muted"}>
                  {s.fired ? s.direction : "no"}
                  {s.fired && s.risk_approved === false ? " (rejected)" : ""}
                </td>
                <td className="reason">{s.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
