import { Fragment, useState } from "react";
import type { Readiness, StrategyEvaluation } from "../types";
import {
  latestEvaluation,
  linkFor,
  setLiveOverride,
  setStrategyEnabled,
  useStrategyLab,
} from "../lib/useStrategyLab";
import { StrategyReport } from "./StrategyReport";

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
const RANK: Record<Readiness, number> = { ready: 2, almost_ready: 1, not_ready: 0 };

function fmt(value: number | null | undefined, digits = 2, suffix = "") {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)}${suffix}`;
}

/** Ranking: readiness first, then how strong the *proven* edge is (CI lower
 * bound - the honest measure, not the flattering point estimate), then sample
 * size as the tiebreak. */
function rankScore(evaluation: StrategyEvaluation | null, readiness: Readiness): number[] {
  return [
    RANK[readiness] ?? 0,
    evaluation?.ci_low ?? -99,
    evaluation?.expectancy_r ?? -99,
    evaluation?.trades_count ?? 0,
  ];
}

export function StrategyLab() {
  const { accounts, strategies, links, evaluations, closedTrades, loading, refresh } =
    useStrategyLab();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const labAccount = accounts.find((a) => a.account_type === "demo") ?? null;
  const liveAccount = accounts.find((a) => a.account_type === "live") ?? null;

  if (loading) return <section className="section"><div className="card">Loading strategies…</div></section>;

  const active = strategies.filter((s) => !s.retired);
  const ranked = [...active].sort((a, b) => {
    const sa = rankScore(labAccount ? latestEvaluation(evaluations, a.name, labAccount.key) : null, a.readiness);
    const sb = rankScore(labAccount ? latestEvaluation(evaluations, b.name, labAccount.key) : null, b.readiness);
    for (let i = 0; i < sa.length; i++) if (sb[i] !== sa[i]) return sb[i] - sa[i];
    return a.name.localeCompare(b.name);
  });

  async function toggle(id: number, next: boolean, live: boolean) {
    setBusy(id);
    if (live) await setLiveOverride(id, next);
    else await setStrategyEnabled(id, next);
    await refresh();
    setBusy(null);
  }

  const readyCount = active.filter((s) => s.readiness === "ready").length;

  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Strategy laboratory</h2>
        <span className="section-note">
          {active.length} active · {readyCount} ready · ranked by proven edge
        </span>
      </div>

      {liveAccount && readyCount === 0 && (
        <div className="banner banner-info" role="status">
          <div className="banner-text">
            <strong>No strategy is Ready, so the live account would place no trades.</strong> That
            is by design — live never falls back to unproven strategies.
          </div>
        </div>
      )}

      <div className="card card-flush">
        <table className="tbl">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Verdict</th>
              <th className="num">Trades</th>
              <th className="num">Win</th>
              <th className="num">Expectancy</th>
              <th className="num">95% CI</th>
              <th className="num">PF</th>
              <th className="num">Max DD</th>
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
              return (
                <Fragment key={strategy.name}>
                  <tr
                    className="row-click"
                    onClick={() => setSelected(open ? null : strategy.name)}
                  >
                    <td>
                      <span className="mono">{strategy.display_name || strategy.name}</span>
                    </td>
                    <td>
                      <span className={`badge ${VERDICT_CLASS[strategy.readiness]}`}>
                        {VERDICT_LABEL[strategy.readiness]}
                      </span>
                    </td>
                    <td className="num">{evaluation?.trades_count ?? 0}</td>
                    <td className="num">{fmt(evaluation?.win_rate, 0, "%")}</td>
                    <td className="num">{fmt(evaluation?.expectancy_r, 3, "R")}</td>
                    <td className="num">
                      {evaluation?.ci_low != null && evaluation?.ci_high != null
                        ? `[${evaluation.ci_low.toFixed(2)}, ${evaluation.ci_high.toFixed(2)}]`
                        : "—"}
                    </td>
                    <td className="num">{fmt(evaluation?.profit_factor)}</td>
                    <td className="num">{fmt(evaluation?.max_drawdown_r, 1, "R")}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {demoLink ? (
                        <label className="switch">
                          <input
                            type="checkbox"
                            checked={demoLink.enabled}
                            disabled={busy === demoLink.id}
                            onChange={(e) => toggle(demoLink.id, e.target.checked, false)}
                          />
                          <span>{demoLink.enabled ? "on" : "off"}</span>
                        </label>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {liveLink ? (
                        <label className="switch">
                          <input
                            type="checkbox"
                            checked={liveLink.enabled}
                            disabled={busy === liveLink.id}
                            onChange={(e) => toggle(liveLink.id, e.target.checked, false)}
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
                    <tr>
                      <td colSpan={10} className="report-cell">
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
    </section>
  );
}
