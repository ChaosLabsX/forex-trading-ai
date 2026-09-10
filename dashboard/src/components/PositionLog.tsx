import { useMemo } from "react";
import type { Trade } from "../types";
import { fmtDateTime, fmtMoney, fmtPrice } from "../lib/format";
import { useShowMore } from "../lib/useShowMore";

const INITIAL_ROWS = 10;
const STEP_ROWS = 25;

/** Result as a multiple of what the trade risked, so a -1.00R stop-out reads
 * the same on a $200 account as on a $200k one. Money answers "what did this
 * cost"; R answers "was this a normal loss or an abnormal one", which is the
 * question a row-by-row log is actually for.
 *
 * risk_amount is captured at open from the INITIAL stop, so trailing never
 * rewrites the denominator. Missing on trades that predate that column - shown
 * as an em dash rather than computed from the current stop, which would give a
 * confident-looking wrong number. */
function rMultiple(t: Trade): number | null {
  if (!t.risk_amount || t.realized_pnl === null) return null;
  return t.realized_pnl / t.risk_amount;
}

function tone(value: number | null): string {
  if (value === null) return "";
  return value > 0 ? "pnl-pos" : value < 0 ? "pnl-neg" : "";
}

type SymbolRow = { symbol: string; trades: number; net: number };

/** Per-symbol totals over the same period, best first. Exactly derivable from
 * the rows above it, so the two can never disagree. */
function bySymbol(trades: Trade[]): SymbolRow[] {
  const rows = new Map<string, SymbolRow>();
  for (const t of trades) {
    if (t.realized_pnl === null) continue;
    const row = rows.get(t.symbol) ?? { symbol: t.symbol, trades: 0, net: 0 };
    row.trades += 1;
    row.net += t.realized_pnl;
    rows.set(t.symbol, row);
  }
  return [...rows.values()].sort((a, b) => b.net - a.net);
}

/** Every closed position in the selected period, one row each.
 *
 * The summary above answers "how did the account do". This answers "which
 * trades did that", which is the only view that shows a total being carried by
 * one outlier - a thing this lab's own research log keeps finding.
 *
 * Deliberately NOT an exit-type column, tempting as it is: the engine records
 * entry but never the exit PRICE, so "stop" vs "target" could only be guessed
 * from the result. R already says it plainly - about -1.00R is a stop-out -
 * without inventing a label the data cannot support. */
export function PositionLog({ trades }: { trades: Trade[] }) {
  const { visible, shown, total, hasMore, showMore } = useShowMore(
    trades,
    INITIAL_ROWS,
    STEP_ROWS
  );
  const symbols = useMemo(() => bySymbol(trades), [trades]);

  if (total === 0) return null;

  return (
    <div className="pnl-log">
      <div className="pnl-log-head">
        <h3 className="pnl-log-title">Positions</h3>
        <span className="pnl-log-count">
          {shown} of {total}
        </span>
      </div>

      <div className="table-scroll">
        <table className="rtable">
          <thead>
            <tr>
              <th>Closed</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Lots</th>
              <th>Entry</th>
              <th>R</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => {
              const pnl = t.realized_pnl;
              const r = rMultiple(t);
              return (
                <tr key={t.id}>
                  <td className="cell-time" data-label="Closed">
                    {t.closed_at ? fmtDateTime(t.closed_at) : "—"}
                  </td>
                  <td className="cell-sym" data-label="Symbol">
                    {t.symbol}
                  </td>
                  <td data-label="Side">
                    <span
                      className={`badge ${t.direction === "LONG" ? "badge-long" : "badge-short"}`}
                    >
                      {t.direction === "LONG" ? "▲ LONG" : "▼ SHORT"}
                    </span>
                  </td>
                  <td className="cell-num" data-label="Lots">
                    {t.lot_size}
                  </td>
                  <td className="cell-num" data-label="Entry">
                    {fmtPrice(t.entry_price)}
                  </td>
                  <td className={`cell-num ${tone(r)}`} data-label="R">
                    {r !== null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}R` : "—"}
                  </td>
                  <td className={`cell-num ${tone(pnl)}`} data-label="Result">
                    <strong>{pnl !== null ? fmtMoney(pnl) : "unknown"}</strong>
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

      {symbols.length > 1 && (
        <>
          <div className="pnl-log-head pnl-log-head-sub">
            <h3 className="pnl-log-title">By symbol</h3>
          </div>
          <div className="table-scroll">
            <table className="rtable">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Trades</th>
                  <th>Net</th>
                </tr>
              </thead>
              <tbody>
                {symbols.map((s) => (
                  <tr key={s.symbol}>
                    <td className="cell-sym" data-label="Symbol">
                      {s.symbol}
                    </td>
                    <td className="cell-num" data-label="Trades">
                      {s.trades}
                    </td>
                    <td className={`cell-num ${tone(s.net)}`} data-label="Net">
                      <strong>{fmtMoney(s.net)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
