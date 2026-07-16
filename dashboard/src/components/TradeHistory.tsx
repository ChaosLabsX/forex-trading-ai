import type { Trade } from "../types";
import { fmtDateTime, fmtMoney, fmtPrice } from "../lib/format";
import { useShowMore } from "../lib/useShowMore";

const INITIAL_ROWS = 5;
const STEP_ROWS = 10;

export function TradeHistory({ trades }: { trades: Trade[] }) {
  const { visible, shown, total, hasMore, showMore } = useShowMore(trades, INITIAL_ROWS, STEP_ROWS);
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Trade history</h2>
        <span className="section-meta">{shown} of {total} closed</span>
      </div>
      <div className="card">
        {trades.length === 0 ? (
          <p className="empty">No closed trades yet - results will appear here.</p>
        ) : (
          <>
          <div className="table-scroll">
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
              {visible.map((t) => {
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
          </div>
          {hasMore && (
            <button className="btn btn-ghost btn-showmore" onClick={showMore}>
              Show more ({total - shown} more)
            </button>
          )}
          </>
        )}
      </div>
    </section>
  );
}
