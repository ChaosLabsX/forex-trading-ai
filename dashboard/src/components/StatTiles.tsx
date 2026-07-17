import type { Trade, Strategy, StrategyEvaluation } from "../types";
import type { AccountHealth } from "../lib/useDashboardData";
import {
  fmtEta,
  latestEvaluation,
  rankStrategies,
  readinessGates,
  READINESS,
  verdictEta,
} from "../lib/useStrategyLab";
import { fmtStrategyName } from "../lib/format";

type Props = {
  health: AccountHealth[];
  openTrades: Trade[];
  strategies: Strategy[];
  evaluations: StrategyEvaluation[];
  /** The lab's closed trades (from useStrategyLab), for the leader's trade-rate
   * ETA - NOT the account-filtered list. */
  closedTrades: Trade[];
  /** Always the DEMO lab, never the filtered account: verdicts derive from the
   * lab by definition, so these tiles must not change meaning when the account
   * filter moves. */
  labAccountKey: string | null;
};

export function StatTiles({ health, openTrades, strategies, evaluations, closedTrades, labAccountKey }: Props) {
  // Headline the engines that are meant to be running; per-account detail lives
  // in the Accounts section.
  const expected = health.filter((h) => h.account.enabled);
  const online = expected.filter((h) => h.online);
  const paused = online.filter((h) => h.paused);

  let engineLabel: string;
  let engineDot: string;
  let engineSub: string;
  if (expected.length === 0) {
    engineLabel = "NONE";
    engineDot = "dot-idle";
    engineSub = "No account is in service";
  } else if (online.length === 0) {
    engineLabel = "OFFLINE";
    engineDot = "dot-crit";
    engineSub = "No engine is reporting";
  } else if (paused.length > 0) {
    engineLabel = "PAUSED";
    engineDot = "dot-warn";
    engineSub = `${paused.length} of ${online.length} engine${online.length === 1 ? "" : "s"} paused`;
  } else {
    engineLabel = "LIVE";
    engineDot = "dot-good";
    engineSub =
      online.length === expected.length
        ? `${online.length} engine${online.length === 1 ? "" : "s"} running`
        : `${online.length}/${expected.length} engines running`;
  }

  const active = strategies.filter((s) => !s.retired);
  const leader = labAccountKey ? rankStrategies(active, evaluations, labAccountKey)[0] ?? null : null;
  const leaderEval =
    leader && labAccountKey ? latestEvaluation(evaluations, leader.name, labAccountKey) : null;
  const readyCount = active.filter((s) => s.readiness === "ready").length;

  const expectancy = leaderEval?.expectancy_r;
  const ciLow = leaderEval?.ci_low;
  const ciHigh = leaderEval?.ci_high;
  // The CI is the test, not the point estimate - so the interval is never
  // rendered without saying what it means.
  const ciSub =
    ciLow != null && ciHigh != null
      ? `95% CI [${ciLow.toFixed(3)}, ${ciHigh.toFixed(3)}] · ${
          ciLow > 0 ? "proven above zero" : "still includes zero"
        }`
      : leaderEval
        ? "CI unavailable - too few trades"
        : "No evaluation yet";

  // How far the leader is along the READY ladder: trades toward the 100 minimum,
  // and how many of the quality gates are met. This is the honest "process"
  // headline - the precise binding reason (verdict_reason) lives one glance down
  // in the lab table's Progress column.
  const leaderGates = readinessGates(leaderEval);
  const leaderGatesMet = leaderGates.filter((g) => g.met).length;
  const leaderTrades = leaderEval?.trades_count ?? 0;
  const leaderEta =
    leader && labAccountKey && leaderEval
      ? verdictEta(closedTrades, leader.name, labAccountKey, leaderEval.trades_count)
      : null;

  return (
    <div className="tiles">
      <div className="tile">
        <div className="tile-label">Engines</div>
        <div className="tile-value">
          <span className={`dot ${engineDot}`} aria-hidden="true" />
          {engineLabel}
        </div>
        <div className="tile-sub">{engineSub}</div>
      </div>

      <div className="tile">
        <div className="tile-label">Open trades</div>
        <div className="tile-value">{openTrades.length}</div>
        <div className="tile-sub">
          {openTrades.length > 0
            ? openTrades.map((t) => t.symbol).join(", ")
            : "No positions open"}
        </div>
      </div>

      <div className="tile">
        <div className="tile-label">Best expectancy</div>
        <div
          className={`tile-value ${
            ciLow != null && ciLow > 0 ? "pnl-pos" : expectancy != null && expectancy < 0 ? "pnl-neg" : ""
          }`}
        >
          {expectancy != null ? `${expectancy.toFixed(3)}R` : "—"}
        </div>
        <div className="tile-sub">{ciSub}</div>
      </div>

      <div className="tile">
        <div className="tile-label">Closest to READY</div>
        <div className="tile-value">
          {readyCount > 0
            ? `${readyCount} READY`
            : leader
              ? <span className="tile-strategy">{fmtStrategyName(leader.display_name || leader.name)}</span>
              : "—"}
        </div>
        <div className="tile-sub">
          {leader
            ? `${leaderTrades} / ${READINESS.minTradesReady} trades · ${leaderGatesMet}/${leaderGates.length} checks passed` +
              (leaderEta ? ` · ${fmtEta(leaderEta)}` : "")
            : "No strategies registered"}
        </div>
      </div>
    </div>
  );
}
