import type { Trade, Strategy, StrategyEvaluation } from "../types";
import type { AccountHealth } from "../lib/useDashboardData";
import { latestEvaluation, rankStrategies } from "../lib/useStrategyLab";

type Props = {
  health: AccountHealth[];
  openTrades: Trade[];
  strategies: Strategy[];
  evaluations: StrategyEvaluation[];
  /** Always the DEMO lab, never the filtered account: verdicts derive from the
   * lab by definition, so these tiles must not change meaning when the account
   * filter moves. */
  labAccountKey: string | null;
};

export function StatTiles({ health, openTrades, strategies, evaluations, labAccountKey }: Props) {
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

  // The evaluator rewrites verdict_reason on EVERY snapshot; strategies.readiness_reason
  // is only rewritten when the verdict actually changes, so it goes stale between
  // changes. For "what is blocking this right now", the snapshot is the honest source.
  const blocker = leaderEval?.verdict_reason ?? "The lab has not evaluated this strategy yet";

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
              ? leader.display_name || leader.name
              : "—"}
        </div>
        <div className="tile-sub">{leader ? blocker : "No strategies registered"}</div>
      </div>
    </div>
  );
}
