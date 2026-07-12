import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import type { Trade } from "../types";

export function OpenTrades() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const { data } = await supabase
        .from("trades")
        .select("*")
        .eq("status", "OPEN")
        .order("opened_at", { ascending: false });
      if (!cancelled) {
        setTrades(data ?? []);
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
      <h2>Open Trades ({trades.length})</h2>
      {loading ? (
        <p>Loading...</p>
      ) : trades.length === 0 ? (
        <p className="muted">No open trades.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Direction</th>
              <th>Lot</th>
              <th>Entry</th>
              <th>Stop</th>
              <th>Target</th>
              <th>Opened</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id}>
                <td>{t.symbol}</td>
                <td className={t.direction === "LONG" ? "long" : "short"}>{t.direction}</td>
                <td>{t.lot_size}</td>
                <td>{t.entry_price}</td>
                <td>{t.stop_loss ?? "-"}</td>
                <td>{t.take_profit ?? "-"}</td>
                <td>{new Date(t.opened_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
