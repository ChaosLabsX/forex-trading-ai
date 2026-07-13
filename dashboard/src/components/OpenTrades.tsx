import type { Trade } from "../types";
import { fmtDateTime, fmtPrice } from "../lib/format";

export function OpenTrades({ trades }: { trades: Trade[] }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Open positions</h2>
        <span className="section-meta">{trades.length} open</span>
      </div>
      <div className="card">
        {trades.length === 0 ? (
          <p className="empty">
            No positions open. The engine opens trades automatically when a signal passes risk
            checks.
          </p>
        ) : (
          <table className="rtable">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Lots</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td className="cell-sym" data-label="Symbol">{t.symbol}</td>
                  <td data-label="Side">
                    <span className={`badge ${t.direction === "LONG" ? "badge-long" : "badge-short"}`}>
                      {t.direction === "LONG" ? "▲ LONG" : "▼ SHORT"}
                    </span>
                  </td>
                  <td className="cell-num" data-label="Lots">{t.lot_size}</td>
                  <td className="cell-num" data-label="Entry">{fmtPrice(t.entry_price)}</td>
                  <td className="cell-num" data-label="Stop">{t.stop_loss !== null ? fmtPrice(t.stop_loss) : "—"}</td>
                  <td className="cell-num" data-label="Target">{t.take_profit !== null ? fmtPrice(t.take_profit) : "—"}</td>
                  <td className="cell-time" data-label="Opened">{fmtDateTime(t.opened_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
