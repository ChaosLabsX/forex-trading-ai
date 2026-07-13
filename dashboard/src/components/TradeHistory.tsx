import type { Trade } from "../types";
import { fmtDateTime, fmtMoney, fmtPrice } from "../lib/format";

export function TradeHistory({ trades }: { trades: Trade[] }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Trade history</h2>
        <span className="section-meta">last {trades.length} closed</span>
      </div>
      <div className="card">
        {trades.length === 0 ? (
          <p className="empty">No closed trades yet - results will appear here.</p>
        ) : (
          <table className="rtable">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>P&amp;L</th>
                <th>Closed</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const pnl = t.realized_pnl;
                return (
                  <tr key={t.id}>
                    <td className="cell-sym" data-label="Symbol">{t.symbol}</td>
                    <td data-label="Side">
                      <span className={`badge ${t.direction === "LONG" ? "badge-long" : "badge-short"}`}>
                        {t.direction === "LONG" ? "▲ LONG" : "▼ SHORT"}
                      </span>
                    </td>
                    <td className="cell-num" data-label="Entry">{fmtPrice(t.entry_price)}</td>
                    <td
                      className={`cell-num ${pnl !== null ? (pnl > 0 ? "pnl-pos" : pnl < 0 ? "pnl-neg" : "") : ""}`}
                      data-label="P&L"
                    >
                      <strong>{pnl !== null ? fmtMoney(pnl) : "unknown"}</strong>
                    </td>
                    <td className="cell-time" data-label="Closed">
                      {t.closed_at ? fmtDateTime(t.closed_at) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
