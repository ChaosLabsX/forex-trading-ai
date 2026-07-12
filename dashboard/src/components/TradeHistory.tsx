import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import type { Trade } from "../types";

export function TradeHistory() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const { data } = await supabase
        .from("trades")
        .select("*")
        .eq("status", "CLOSED")
        .order("closed_at", { ascending: false })
        .limit(50);
      setTrades(data ?? []);
      setLoading(false);
    }
    load();
  }, []);

  const closedWithPnl = trades.filter((t) => t.realized_pnl !== null);
  const wins = closedWithPnl.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const totalPnl = closedWithPnl.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  const winRate = closedWithPnl.length ? (wins / closedWithPnl.length) * 100 : null;

  return (
    <div className="card">
      <h2>Trade History</h2>
      {loading ? (
        <p>Loading...</p>
      ) : (
        <>
          <div className="stats-row">
            <div>
              <span className="stat-value">{closedWithPnl.length}</span>
              <span className="stat-label">closed trades</span>
            </div>
            <div>
              <span className="stat-value">{winRate !== null ? `${winRate.toFixed(0)}%` : "-"}</span>
              <span className="stat-label">win rate</span>
            </div>
            <div>
              <span className={`stat-value ${totalPnl >= 0 ? "long" : "short"}`}>
                {totalPnl >= 0 ? "+" : ""}
                {totalPnl.toFixed(2)}
              </span>
              <span className="stat-label">total P&amp;L</span>
            </div>
          </div>
          {trades.length === 0 ? (
            <p className="muted">No closed trades yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Direction</th>
                  <th>Entry</th>
                  <th>P&amp;L</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.symbol}</td>
                    <td className={t.direction === "LONG" ? "long" : "short"}>{t.direction}</td>
                    <td>{t.entry_price}</td>
                    <td className={(t.realized_pnl ?? 0) >= 0 ? "long" : "short"}>
                      {t.realized_pnl !== null ? t.realized_pnl.toFixed(2) : "unknown"}
                    </td>
                    <td>{t.closed_at ? new Date(t.closed_at).toLocaleString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
