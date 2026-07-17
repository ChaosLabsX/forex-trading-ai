import { Fragment, useState } from "react";
import type { Account, Readiness, Strategy, StrategyAccount, StrategyEvaluation, Trade } from "../types";
import {
  fmtEta,
  latestEvaluation,
  linkFor,
  rankStrategies,
  setStrategyEnabled,
  verdictEta,
} from "../lib/useStrategyLab";
import { StrategyReport } from "./StrategyReport";
import { GateList, TradeProgress } from "./Readiness";
import { fmtStrategyName } from "../lib/format";

const VERDICT_LABEL: Record<Readiness, string> = {
  ready: "READY",
  almost_ready: "ALMOST",
  not_ready: "NOT READY",
};
const VERDICT_CLASS: Record<Readiness, string> = {
  ready: "badge-ready",
  almost_ready: "badge-almost",
  not_ready: "badge-notready",
};

function fmt(value: number | null | undefined, digits = 2, suffix = "") {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)}${suffix}`;
}

type Props = {
  accounts: Account[];
  strategies: Strategy[];
  links: StrategyAccount[];
  evaluations: StrategyEvaluation[];
  closedTrades: Trade[];
  refresh: () => Promise<void>;
};

export function StrategyLab({ accounts, strategies, links, evaluations, closedTrades, refresh }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const labAccount = accounts.find((a) => a.account_type === "demo") ?? null;
  const liveAccount = accounts.find((a) => a.account_type === "live") ?? null;

  const active = strategies.filter((s) => !s.retired);
  const ranked = labAccount ? rankStrategies(active, evaluations, labAccount.key) : active;

  async function toggle(id: number, next: boolean) {
    setBusy(id);
    await setStrategyEnabled(id, next);
    await refresh();
    setBusy(null);
  }

  const readyCount = active.filter((s) => s.readiness === "ready").length;
  const almostCount = active.filter((s) => s.readiness === "almost_ready").length;
  const notReadyCount = active.filter((s) => s.readiness === "not_ready").length;

  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Strategy laboratory</h2>
        <span className="section-note">ranked by proven edge</span>
      </div>

      <div className="lab-summary">
        <div className="lab-stat">
          <strong>{active.length}</strong>
          <span>Total</span>
        </div>
        <div className="lab-stat is-ready">
          <strong>{readyCount}</strong>
          <span>Ready</span>
        </div>
        <div className="lab-stat is-almost">
          <strong>{almostCount}</strong>
          <span>Almost ready</span>
        </div>
        <div className="lab-stat is-not">
          <strong>{notReadyCount}</strong>
          <span>Not ready</span>
        </div>
      </div>

      {liveAccount && readyCount === 0 && (
        <div className="banner banner-info" role="status">
          <div className="banner-text">
            <strong>No strategy is Ready, so the live account would place no trades.</strong> That
            is by design — live never falls back to unproven strategies.
          </div>
        </div>
      )}

      <div className="card">
        <div className="table-scroll">
        <table className="rtable lab-table">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Verdict</th>
              <th>Trades</th>
              <th>Win</th>
              <th>Expectancy</th>
              <th>95% CI</th>
              <th>PF</th>
              <th>Max DD</th>
              <th>Progress to READY</th>
              <th>Demo</th>
              <th>Live</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((strategy) => {
              const evaluation = labAccount
                ? latestEvaluation(evaluations, strategy.name, labAccount.key)
                : null;
              const demoLink = labAccount ? linkFor(links, strategy.name, labAccount.key) : null;
              const liveLink = liveAccount ? linkFor(links, strategy.name, liveAccount.key) : null;
              const open = selected === strategy.name;
              // ETA always projects the LAB's rate - verdicts derive from the
              // demo account by definition, whatever the account filter shows.
              const eta =
                labAccount && evaluation
                  ? verdictEta(closedTrades, strategy.name, labAccount.key, evaluation.trades_count)
                  : null;
              return (
                <Fragment key={strategy.name}>
                  <tr
                    className="row-click"
                    onClick={() => setSelected(open ? null : strategy.name)}
                  >
                    <td className="cell-sym" data-label="Strategy">
                      {fmtStrategyName(strategy.display_name || strategy.name)}
                    </td>
                    <td data-label="Verdict">
                      <span className={`badge ${VERDICT_CLASS[strategy.readiness]}`}>
                        {VERDICT_LABEL[strategy.readiness]}
                      </span>
                    </td>
                    <td className="cell-num" data-label="Trades">
                      <TradeProgress
                        trades={evaluation?.trades_count ?? 0}
                        eta={eta ? fmtEta(eta) : null}
                      />
                    </td>
                    <td className="cell-num" data-label="Win">{fmt(evaluation?.win_rate, 0, "%")}</td>
                    <td className="cell-num" data-label="Expectancy">
                      {fmt(evaluation?.expectancy_r, 3, "R")}
                    </td>
                    <td className="cell-num" data-label="95% CI">
                      {evaluation?.ci_low != null && evaluation?.ci_high != null
                        ? `[${evaluation.ci_low.toFixed(2)}, ${evaluation.ci_high.toFixed(2)}]`
                        : "—"}
                    </td>
                    <td className="cell-num" data-label="PF">{fmt(evaluation?.profit_factor)}</td>
                    <td className="cell-num" data-label="Max DD">
                      {fmt(evaluation?.max_drawdown_r, 1, "R")}
                    </td>
                    {/* The gate ladder makes the shape scannable; the evaluator's
                        verdict_reason underneath is the precise binding constraint.
                        verdict_reason is rewritten every snapshot (unlike
                        strategies.readiness_reason, which only changes when the
                        verdict does), so it always answers "what blocks it now". */}
                    <td className="cell-reason cell-wide" data-label="Progress to READY">
                      {evaluation ? (
                        <>
                          <GateList evaluation={evaluation} />
                          {evaluation.verdict_reason && (
                            <div className="gate-reason">{evaluation.verdict_reason}</div>
                          )}
                        </>
                      ) : (
                        "Not evaluated yet"
                      )}
                    </td>
                    <td data-label="Demo" onClick={(e) => e.stopPropagation()}>
                      {demoLink ? (
                        <label className="switch">
                          <input
                            type="checkbox"
                            checked={demoLink.enabled}
                            disabled={busy === demoLink.id}
                            onChange={(e) => toggle(demoLink.id, e.target.checked)}
                          />
                          <span>{demoLink.enabled ? "on" : "off"}</span>
                        </label>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td data-label="Live" onClick={(e) => e.stopPropagation()}>
                      {liveLink ? (
                        <label className="switch">
                          <input
                            type="checkbox"
                            checked={liveLink.enabled}
                            disabled={busy === liveLink.id}
                            onChange={(e) => toggle(liveLink.id, e.target.checked)}
                          />
                          <span>
                            {liveLink.enabled
                              ? strategy.readiness === "ready"
                                ? "on"
                                : "on (blocked)"
                              : "off"}
                          </span>
                        </label>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                  {open && (
                    <tr className="report-row">
                      <td colSpan={11} className="report-cell">
                        <StrategyReport
                          strategy={strategy}
                          accounts={accounts}
                          evaluations={evaluations}
                          closedTrades={closedTrades}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>
    </section>
  );
}
