import type { StrategyEvaluation } from "../types";
import { READINESS, readinessGates, readinessScore } from "../lib/useStrategyLab";

/** One number for "how close is this strategy to READY", with the ladder drawn
 * as notches so the percentage reads as what it is: gates cleared out of five.
 *
 * Green only at 100%. Below that the fill is the same neutral accent as
 * TradeProgress, for the same reason - being 80% of the way along a process is
 * not evidence of an edge, and colouring it as success would say it is.
 *
 * The tooltip carries the caveat the number cannot carry on its own: four of
 * the five gates are pass/fail on merit, so this is a snapshot, not a countdown,
 * and it can move backwards. */
export function ReadinessMeter({ evaluation }: { evaluation: StrategyEvaluation | null }) {
  const { pct, met, total, complete } = readinessScore(evaluation);
  const share = 100 / total;
  // Notches derived from the gate count, so adding a sixth gate re-spaces them
  // instead of leaving four hardcoded marks describing a five-step ladder.
  const notches = Array.from({ length: total - 1 }, (_, i) => (i + 1) * share);

  return (
    <div
      className="rmeter"
      title={
        `${pct}% of the way to READY - ${met} of ${total} checks passed.\n` +
        `Each check is worth ${share.toFixed(0)}%. Only the trade-count check fills gradually; ` +
        `the other four are pass/fail on merit.\n` +
        `This can go DOWN: more trades can break a check that was passing.`
      }
    >
      <div className="rmeter-head">
        <strong className={complete ? "rmeter-pct is-ready" : "rmeter-pct"}>{pct}%</strong>
        <span className="rmeter-sub">
          {met}/{total} checks passed
        </span>
      </div>
      <div
        className="rmeter-track"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${pct}% of the way to a READY verdict, ${met} of ${total} checks passed`}
      >
        <div
          className={complete ? "rmeter-fill is-ready" : "rmeter-fill"}
          style={{ width: `${pct}%` }}
        />
        {notches.map((left) => (
          <div key={left} className="rmeter-notch" style={{ left: `${left}%` }} />
        ))}
      </div>
    </div>
  );
}

/** Trades accumulated toward the READY minimum (100), with a tick at 30 - the
 * point engine/evaluator.py first renders any verdict at all. The fill is a
 * neutral accent, deliberately NOT green: piling up trades is progress through
 * the process, not evidence of an edge. Green here would imply the strategy is
 * doing well simply by trading a lot, which is exactly the misread the research
 * log warns against. */
export function TradeProgress({ trades, eta }: { trades: number; eta?: string | null }) {
  const target = READINESS.minTradesReady;
  const pct = Math.max(0, Math.min(100, (trades / target) * 100));
  const tickPct = (READINESS.minTradesAlmost / target) * 100;
  return (
    <div
      className="tprog"
      title={`${trades} of ${target} closed trades · first verdict at ${READINESS.minTradesAlmost}`}
    >
      <div className="tprog-label">
        <strong>{trades}</strong>
        <span> / {target}</span>
      </div>
      <div
        className="tprog-track"
        role="img"
        aria-label={`${trades} of ${target} trades toward a READY verdict`}
      >
        <div className="tprog-fill" style={{ width: `${pct}%` }} />
        <div className="tprog-tick" style={{ left: `${tickPct}%` }} title="30 trades: first verdict" />
      </div>
      {/* ETA to the sample minimum only - deliberately not "READY in Nd".
          Reaching 100 trades is a matter of waiting; passing the quality
          gates is not, and the wording must never conflate the two. */}
      {eta && <div className="tprog-eta" title="Projected from the last 7 days' counted trades">{eta}</div>}
    </div>
  );
}

/** The four quality gates as met/unmet checkpoints. Pairs a symbol with colour
 * (never colour alone) so it reads without relying on hue. This is a scannable
 * summary of the shape; the evaluator's verdict_reason remains the precise
 * "why", shown alongside it. */
export function GateList({ evaluation }: { evaluation: StrategyEvaluation | null }) {
  const gates = readinessGates(evaluation);
  return (
    <ul className="gates">
      {gates.map((g) => (
        <li key={g.key} className={g.met ? "gate-item is-met" : "gate-item is-unmet"}>
          <span className="gate-mark" aria-hidden="true">
            {g.met ? "✓" : "○"}
          </span>
          {g.label}
        </li>
      ))}
    </ul>
  );
}
