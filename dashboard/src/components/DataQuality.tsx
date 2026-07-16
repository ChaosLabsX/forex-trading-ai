import type { Account } from "../types";
import { useDataQuality, type DataQualityRow } from "../lib/useDataQuality";

const CATEGORY_LABEL: Record<"voided" | "unknownPnl" | "missingRisk", string> = {
  voided: "voided",
  unknownPnl: "unknown P&L",
  missingRisk: "missing risk data",
};

const CATEGORY_TITLE: Record<"voided" | "unknownPnl" | "missingRisk", string> = {
  voided: "Marked untrustworthy by a manual repair - excluded from every statistic.",
  unknownPnl: "Closed, but MT5 never returned a P&L - excluded from every statistic. Permanent: no retry once a trade leaves OPEN.",
  missingRisk: "Has real P&L but no captured risk_amount - invisible to trades_count/expectancy/CI/profit-factor, though still counted in the raw dollar total.",
};

function RowBreakdown({ row }: { row: DataQualityRow }) {
  const parts: Array<[keyof typeof CATEGORY_LABEL, number]> = (
    ["voided", "unknownPnl", "missingRisk"] as const
  )
    .map((k) => [k, row[k]] as [typeof k, number])
    .filter(([, n]) => n > 0);

  return (
    <div className="dq-row">
      <span className="dq-row-account">{row.accountLabel}</span>
      <span className="dq-row-detail">
        {parts.map(([key, n]) => (
          <span key={key} className="badge badge-warn" title={CATEGORY_TITLE[key]}>
            {n} {CATEGORY_LABEL[key]}
          </span>
        ))}
        <span className="dq-row-context">
          of {row.closedTotal} closed
        </span>
      </span>
    </div>
  );
}

/** Always-on health check for the thing the READY verdict actually depends
 * on: whether closed trades are landing in the stats or silently vanishing
 * from them. A dead lab and a lab quietly excluding everything it "collects"
 * read identically from the tiles alone - this exists so that gap can never
 * be invisible again. Quiet by design when clean (one line, no card); loud
 * when not (see docs/research-log.md's own rule: a null result costs nothing,
 * a SILENT one costs the whole point of the lab). */
export function DataQuality({ accounts }: { accounts: Account[] }) {
  const { rows, loading } = useDataQuality(accounts);

  if (loading || rows.length === 0) return null;

  const totalClosed = rows.reduce((sum, r) => sum + r.closedTotal, 0);
  const totalIssues = rows.reduce((sum, r) => sum + r.voided + r.unknownPnl + r.missingRisk, 0);
  const affected = rows.filter((r) => r.voided + r.unknownPnl + r.missingRisk > 0);

  if (totalIssues === 0) {
    return (
      <div className="dq-clean" title="Every closed trade counted toward its strategy's statistics - none voided, none missing P&L, none missing risk data.">
        <span className="dot dot-good" aria-hidden="true" />
        Data quality — 0 excluded across {totalClosed} closed trades
      </div>
    );
  }

  return (
    <div className="banner banner-crit" role="alert">
      <span className="dot dot-crit banner-dot" aria-hidden="true" />
      <div className="banner-text">
        <strong>
          {totalIssues} closed trade{totalIssues === 1 ? "" : "s"} excluded from statistics
          {affected.length === 1 ? ` on ${affected[0].accountLabel}` : ` across ${affected.length} accounts`}.
        </strong>{" "}
        These trades don't count toward any strategy's trade total, expectancy, or CI - a strategy
        can look stalled or slow to reach READY for a reason that has nothing to do with its edge.
        <div className="dq-rows">
          {affected.map((row) => (
            <RowBreakdown key={row.accountKey} row={row} />
          ))}
        </div>
      </div>
    </div>
  );
}
