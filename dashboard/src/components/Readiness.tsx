import type { StrategyEvaluation } from "../types";
import { READINESS, readinessGates } from "../lib/useStrategyLab";

/** Trades accumulated toward the READY minimum (100), with a tick at 30 - the
 * point engine/evaluator.py first renders any verdict at all. The fill is a
 * neutral accent, deliberately NOT green: piling up trades is progress through
 * the process, not evidence of an edge. Green here would imply the strategy is
 * doing well simply by trading a lot, which is exactly the misread the research
 * log warns against. */
export function TradeProgress({ trades }: { trades: number }) {
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
        <li key={g.key} className={g.met ? "gate is-met" : "gate is-unmet"}>
          <span className="gate-mark" aria-hidden="true">
            {g.met ? "✓" : "○"}
          </span>
          {g.label}
        </li>
      ))}
    </ul>
  );
}
