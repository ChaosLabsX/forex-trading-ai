import type { Heartbeat, Trade } from "../types";
import { fmtAgo, fmtMoney } from "../lib/format";

const STALE_AFTER_MS = 3 * 60 * 1000; // heartbeats are sent every 60s

type Props = {
  heartbeat: Heartbeat | null;
  openTrades: Trade[];
  closedTrades: Trade[];
};

export function StatTiles({ heartbeat, openTrades, closedTrades }: Props) {
  const withPnl = closedTrades.filter((t) => t.realized_pnl !== null);
  const wins = withPnl.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const losses = withPnl.length - wins;
  const totalPnl = withPnl.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  const winRate = withPnl.length ? Math.round((wins / withPnl.length) * 100) : null;

  const heartbeatAge = heartbeat ? Date.now() - new Date(heartbeat.created_at).getTime() : null;
  const engineLive = heartbeatAge !== null && heartbeatAge <= STALE_AFTER_MS;

  let engineLabel: string;
  let engineDot: string;
  let engineSub: string;
  if (!heartbeat) {
    engineLabel = "NO DATA";
    engineDot = "dot-warn";
    engineSub = "No heartbeat received yet";
  } else if (!engineLive) {
    engineLabel = "OFFLINE";
    engineDot = "dot-crit";
    engineSub = `Last heartbeat ${fmtAgo(heartbeat.created_at)}`;
  } else if (heartbeat.status === "paused") {
    engineLabel = "PAUSED";
    engineDot = "dot-warn";
    engineSub = "Not opening new trades";
  } else if (!heartbeat.broker_connected) {
    engineLabel = "LIVE";
    engineDot = "dot-warn";
    engineSub = "Broker disconnected - reconnecting";
  } else {
    engineLabel = "LIVE";
    engineDot = "dot-good";
    engineSub = `Broker connected · ${fmtAgo(heartbeat.created_at)}`;
  }

  return (
    <div className="tiles">
      <div className="tile">
        <div className="tile-label">Engine</div>
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
          {withPnl.length > 0 ? `Across ${withPnl.length} closed trade${withPnl.length === 1 ? "" : "s"}` : "No closed trades yet"}
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
