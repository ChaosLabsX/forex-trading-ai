import { useMemo, useState } from "react";
import type { Account, Trade } from "../types";
import {
  headline,
  inPeriod,
  startOfMonth,
  startOfYear,
  summarize,
  useHistoryRange,
  type Period,
  type PeriodMode,
} from "../lib/usePnlReport";
import { fmtMoney } from "../lib/format";

const MODES: Array<[PeriodMode, string]> = [
  ["month", "Month"],
  ["year", "Year"],
  ["custom", "Custom"],
  ["all", "All"],
];

const monthFmt = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
const dayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

function isoDay(d: Date): string {
  // Local yyyy-mm-dd. toISOString() would shift the day for anyone east or west
  // of UTC, which is how a date picker ends up one day off.
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function stepped(anchor: Date, mode: PeriodMode, by: number): Date {
  return mode === "year"
    ? new Date(anchor.getFullYear() + by, 0, 1)
    : new Date(anchor.getFullYear(), anchor.getMonth() + by, 1);
}

function periodTitle(p: Period): string {
  if (p.mode === "all") return "All time";
  if (p.mode === "month") return monthFmt.format(p.anchor);
  if (p.mode === "year") return String(p.anchor.getFullYear());
  if (!p.from && !p.to) return "Pick a date range";
  const from = p.from ? dayFmt.format(new Date(`${p.from}T00:00:00`)) : "the start";
  const to = p.to ? dayFmt.format(new Date(`${p.to}T00:00:00`)) : "now";
  return `${from} – ${to}`;
}

type Props = {
  account: Account;
  trades: Trade[];
  loading: boolean;
  /** Open positions on this account. Their floating P&L is NOT in the total -
   * said out loud rather than left for the user to discover. */
  openCount: number;
};

/** Realized P&L for one account over a period the user picks.
 *
 * The headline follows the house convention already used for every Telegram
 * trade alert (engine/reporting.py): a winning period is reported BEFORE fees,
 * a losing one ALL-IN. Whether it won or lost is decided by the net, so costs
 * can turn a nominal gain into a loss and the panel will say so.
 *
 * Both figures are always on screen underneath. A headline showing gross while
 * hiding net would be a money figure that flatters - the split row exists so
 * the number that actually moved the balance is never more than a glance away. */
export function PnlReport({ account, trades, loading, openCount }: Props) {
  const now = useMemo(() => new Date(), []);
  const [period, setPeriod] = useState<Period>({
    mode: "month",
    anchor: startOfMonth(new Date()),
    from: "",
    to: "",
  });

  const { earliest } = useHistoryRange(trades);
  const inRange = useMemo(
    () => trades.filter((t) => t.closed_at !== null && inPeriod(t.closed_at, period)),
    [trades, period]
  );
  const summary = useMemo(() => summarize(inRange), [inRange]);
  const { value, basis } = headline(summary);

  const stepping = period.mode === "month" || period.mode === "year";
  // Stop the arrows at the edges of real history rather than let them walk into
  // empty decades in either direction.
  const ceiling = period.mode === "year" ? startOfYear(now) : startOfMonth(now);
  const floor = earliest
    ? period.mode === "year"
      ? startOfYear(earliest)
      : startOfMonth(earliest)
    : // No history yet (a freshly funded account): there is nothing behind the
      // current period to step back into, so both arrows rest. They come alive
      // on their own the moment the first trade closes.
      ceiling;
  const canBack = stepping && period.anchor > floor;
  const canForward = stepping && period.anchor < ceiling;

  function setMode(mode: PeriodMode) {
    setPeriod((p) => ({
      ...p,
      mode,
      // Re-anchor when switching, so "Year" after browsing back to March never
      // lands on a year you were not looking at.
      anchor: mode === "year" ? startOfYear(p.anchor) : startOfMonth(p.anchor),
      from: p.from || (earliest ? isoDay(earliest) : ""),
      to: p.to || isoDay(now),
    }));
  }

  const tone = summary.net > 0 ? "pnl-pos" : summary.net < 0 ? "pnl-neg" : "";

  return (
    <section className="pnl" aria-label={`Profit and loss, ${account.label}`}>
      <div className="pnl-head">
        <div className="pnl-scope">
          <span className="badge badge-live">LIVE</span>
          <span className="pnl-account">{account.label}</span>
        </div>
        <div className="pnl-modes" role="tablist" aria-label="Reporting period">
          {MODES.map(([m, label]) => (
            <button
              key={m}
              role="tab"
              aria-selected={period.mode === m}
              className={`pnl-mode ${period.mode === m ? "is-active" : ""}`}
              onClick={() => setMode(m)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="pnl-nav">
        <button
          className="pnl-arrow"
          onClick={() => setPeriod((p) => ({ ...p, anchor: stepped(p.anchor, p.mode, -1) }))}
          disabled={!canBack}
          aria-label={period.mode === "year" ? "Previous year" : "Previous month"}
        >
          &#9664;
        </button>
        <span className="pnl-period">{periodTitle(period)}</span>
        <button
          className="pnl-arrow"
          onClick={() => setPeriod((p) => ({ ...p, anchor: stepped(p.anchor, p.mode, 1) }))}
          disabled={!canForward}
          aria-label={period.mode === "year" ? "Next year" : "Next month"}
        >
          &#9654;
        </button>
      </div>

      {period.mode === "custom" && (
        <div className="pnl-custom">
          <label>
            <span>From</span>
            <input
              type="date"
              value={period.from}
              max={period.to || undefined}
              onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))}
            />
          </label>
          <label>
            <span>To</span>
            <input
              type="date"
              value={period.to}
              min={period.from || undefined}
              onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))}
            />
          </label>
        </div>
      )}

      {loading ? (
        <div className="pnl-loading">
          <div className="spinner" aria-label="Loading" />
        </div>
      ) : summary.trades === 0 ? (
        <p className="pnl-empty">
          No closed trades in this period.
          {openCount > 0 &&
            ` ${openCount} position${openCount === 1 ? " is" : "s are"} still open.`}
        </p>
      ) : (
        <>
          <div className={`pnl-figure ${tone}`}>{fmtMoney(value)}</div>
          <div className="pnl-basis">
            {basis === "gross"
              ? "profit before fees"
              : summary.fees !== null
                ? "loss including fees"
                : "net result"}
          </div>

          <div className="pnl-split">
            <div>
              <span>Gross</span>
              <strong>{summary.gross !== null ? fmtMoney(summary.gross) : "—"}</strong>
            </div>
            <div>
              <span>Fees</span>
              <strong>{summary.fees !== null ? fmtMoney(summary.fees) : "unknown"}</strong>
            </div>
            <div>
              <span>Net to account</span>
              <strong className={tone}>{fmtMoney(summary.net)}</strong>
            </div>
          </div>

          <div className="pnl-stats">
            <div>
              <span>Trades</span>
              <strong>{summary.trades}</strong>
            </div>
            <div>
              <span>Won / lost</span>
              <strong>
                {summary.wins} / {summary.losses}
                {summary.breakeven > 0 ? ` (+${summary.breakeven} flat)` : ""}
              </strong>
            </div>
            <div>
              <span>Win rate</span>
              <strong>
                {summary.winRate !== null ? `${Math.round(summary.winRate * 100)}%` : "—"}
              </strong>
            </div>
            <div>
              <span>Best / worst</span>
              <strong>
                {summary.best !== null ? fmtMoney(summary.best) : "—"}
                {" / "}
                {summary.worst !== null ? fmtMoney(summary.worst) : "—"}
              </strong>
            </div>
          </div>

          <p className="pnl-note">
            Realized results only
            {openCount === 0
              ? " - no positions are open."
              : ` - ${openCount} open position${openCount === 1 ? "" : "s"} not counted.`}
            {summary.missingBreakdown > 0 &&
              ` Fees unknown for ${summary.missingBreakdown} of ${summary.trades} trades (closed before fee tracking), so gross is not shown.`}
            {summary.unknownPnl > 0 &&
              ` ${summary.unknownPnl} trade${summary.unknownPnl === 1 ? "" : "s"} closed without a result from MT5 and ${summary.unknownPnl === 1 ? "is" : "are"} excluded.`}
          </p>
        </>
      )}
    </section>
  );
}
