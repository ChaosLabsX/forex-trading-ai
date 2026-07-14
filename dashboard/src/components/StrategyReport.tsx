import type { Account, Strategy, StrategyEvaluation, Trade } from "../types";
import { latestEvaluation, rSeries } from "../lib/useStrategyLab";

type Props = {
  strategy: Strategy;
  accounts: Account[];
  evaluations: StrategyEvaluation[];
  closedTrades: Trade[];
};

function fmt(v: number | null | undefined, d = 2, suffix = "") {
  return v === null || v === undefined ? "—" : `${v.toFixed(d)}${suffix}`;
}

/** Cumulative-R equity curve as a sparkline. R (not dollars) because it's the
 * only scale on which EURUSD and XAUUSD are comparable. */
function EquityCurve({ r }: { r: number[] }) {
  if (r.length < 2) return <div className="chart-empty">Not enough closed trades to plot yet</div>;
  const cumulative: number[] = [];
  let total = 0;
  for (const value of r) {
    total += value;
    cumulative.push(total);
  }
  const min = Math.min(0, ...cumulative);
  const max = Math.max(0, ...cumulative);
  const span = max - min || 1;
  const W = 560;
  const H = 90;
  const x = (i: number) => (i / (cumulative.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / span) * H;
  const points = cumulative.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const zeroY = y(0);
  const end = cumulative[cumulative.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="spark" role="img"
         aria-label={`Cumulative R equity curve, ending at ${end.toFixed(2)}R`}>
      <line x1="0" y1={zeroY} x2={W} y2={zeroY} className="spark-zero" />
      <polyline points={points} className={end >= 0 ? "spark-line pos" : "spark-line neg"} />
    </svg>
  );
}

/** The actual edge test: does the confidence interval clear zero? */
function CiBar({ low, high }: { low: number | null; high: number | null }) {
  if (low === null || high === null) return <div className="chart-empty">No confidence interval yet</div>;
  const bound = Math.max(1, Math.abs(low), Math.abs(high)) * 1.15;
  const W = 560;
  const H = 44;
  const x = (v: number) => ((v + bound) / (2 * bound)) * W;
  const proven = low > 0;
  const negative = high < 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="spark" role="img"
         aria-label={`95% confidence interval from ${low.toFixed(3)} to ${high.toFixed(3)} R per trade`}>
      <line x1={x(0)} y1="4" x2={x(0)} y2={H - 12} className="ci-zero" />
      <line x1={x(low)} y1={H / 2 - 4} x2={x(high)} y2={H / 2 - 4}
            className={proven ? "ci-bar pos" : negative ? "ci-bar neg" : "ci-bar mid"} />
      <text x={x(0)} y={H - 1} textAnchor="middle" className="ci-label">0</text>
    </svg>
  );
}

function AccountPanel({
  account, strategy, evaluations, closedTrades,
}: { account: Account; strategy: Strategy; evaluations: StrategyEvaluation[]; closedTrades: Trade[] }) {
  const evaluation = latestEvaluation(evaluations, strategy.name, account.key);
  const r = rSeries(closedTrades, strategy.name, account.key);
  const isLive = account.account_type === "live";

  return (
    <div className="report-panel">
      <div className="report-panel-head">
        <span className={`badge ${isLive ? "badge-live" : "badge-demo"}`}>
          {account.account_type.toUpperCase()}
        </span>
        <span className="report-panel-name">{account.label}</span>
      </div>

      {!evaluation || evaluation.trades_count === 0 ? (
        <div className="chart-empty">
          No evaluated trades on this account yet
          {isLive ? " — live trading is blocked until position sizing exists." : "."}
        </div>
      ) : (
        <>
          <div className="metrics">
            <div><span>Trades</span><strong>{evaluation.trades_count}</strong></div>
            <div><span>Win rate</span><strong>{fmt(evaluation.win_rate, 0, "%")}</strong></div>
            <div><span>Expectancy</span><strong>{fmt(evaluation.expectancy_r, 3, "R")}</strong></div>
            <div><span>Profit factor</span><strong>{fmt(evaluation.profit_factor)}</strong></div>
            <div><span>Avg win</span><strong>{fmt(evaluation.avg_win_r, 2, "R")}</strong></div>
            <div><span>Avg loss</span><strong>{fmt(evaluation.avg_loss_r, 2, "R")}</strong></div>
            <div><span>Max drawdown</span><strong>{fmt(evaluation.max_drawdown_r, 1, "R")}</strong></div>
            <div><span>Worst streak</span><strong>{evaluation.longest_loss_streak ?? "—"}</strong></div>
            <div><span>Net P&amp;L</span>
              <strong className={(evaluation.total_net_pnl ?? 0) >= 0 ? "pnl-pos" : "pnl-neg"}>
                {evaluation.total_net_pnl === null ? "—" : `$${evaluation.total_net_pnl.toFixed(2)}`}
              </strong>
            </div>
          </div>

          <div className="chart-label">Expectancy 95% CI — an edge is only proven if the bar clears zero</div>
          <CiBar low={evaluation.ci_low} high={evaluation.ci_high} />

          <div className="chart-label">Cumulative R</div>
          <EquityCurve r={r} />
        </>
      )}
    </div>
  );
}

export function StrategyReport({ strategy, accounts, evaluations, closedTrades }: Props) {
  return (
    <div className="report">
      <p className="report-verdict">
        <strong>Verdict:</strong> {strategy.readiness_reason ?? "not evaluated yet"}
      </p>
      {strategy.description && <p className="report-desc">{strategy.description}</p>}
      <div className="report-grid">
        {accounts.map((account) => (
          <AccountPanel
            key={account.key}
            account={account}
            strategy={strategy}
            evaluations={evaluations}
            closedTrades={closedTrades}
          />
        ))}
      </div>
    </div>
  );
}
