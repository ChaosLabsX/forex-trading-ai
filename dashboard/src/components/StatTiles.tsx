import type { Trade } from "../types";
import type { AccountHealth } from "../lib/useDashboardData";
import { fmtMoney } from "../lib/format";

type Props = {
  health: AccountHealth[];
  openTrades: Trade[];
  closedTrades: Trade[];
};

export function StatTiles({ health, openTrades, closedTrades }: Props) {
  const withPnl = closedTrades.filter((t) => t.realized_pnl !== null);
  const wins = withPnl.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const losses = withPnl.length - wins;
  const totalPnl = withPnl.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  const winRate = withPnl.length ? Math.round((wins / withPnl.length) * 100) : null;

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
        <div className="tile-label">Total P&amp;L</div>
        <div className={`tile-value ${totalPnl > 0 ? "pnl-pos" : totalPnl < 0 ? "pnl-neg" : ""}`}>
          {fmtMoney(totalPnl)}
        </div>
        <div className="tile-sub">
          {withPnl.length > 0
            ? `Across ${withPnl.length} closed trade${withPnl.length === 1 ? "" : "s"}`
            : "No closed trades yet"}
        </div>
      </div>

      <div className="tile">
        <div className="tile-label">Win rate</div>
        <div className="tile-value">{winRate !== null ? `${winRate}%` : "—"}</div>
        <div className="tile-sub">
          {withPnl.length > 0 ? `${wins} won · ${losses} lost` : "No closed trades yet"}
        </div>
      </div>
    </div>
  );
}
