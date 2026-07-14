import type { Session } from "@supabase/supabase-js";
import type { AccountHealth } from "../lib/useDashboardData";
import { fmtAgo } from "../lib/format";
import { Controls } from "./Controls";

type Props = { session: Session; health: AccountHealth[] };

function statusOf(h: AccountHealth): { label: string; dot: string; sub: string } {
  if (!h.heartbeat) {
    return {
      label: "NOT RUNNING",
      dot: "dot-idle",
      sub: h.account.enabled ? "No heartbeat received yet" : "Registered, no engine deployed yet",
    };
  }
  if (!h.online) {
    return { label: "OFFLINE", dot: "dot-crit", sub: `Last heartbeat ${fmtAgo(h.heartbeat.created_at)}` };
  }
  if (h.paused) return { label: "PAUSED", dot: "dot-warn", sub: "Not opening new trades" };
  if (!h.heartbeat.broker_connected) {
    return { label: "LIVE", dot: "dot-warn", sub: "Broker disconnected - reconnecting" };
  }
  return { label: "LIVE", dot: "dot-good", sub: `Broker connected · ${fmtAgo(h.heartbeat.created_at)}` };
}

export function Engines({ session, health }: Props) {
  if (health.length === 0) return null;

  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Accounts &amp; engines</h2>
        <span className="section-note">{health.length} registered</span>
      </div>

      <div className="engine-grid">
        {health.map((h) => {
          const status = statusOf(h);
          const isLive = h.account.account_type === "live";
          return (
            <div className="card engine-card" key={h.account.key}>
              <div className="engine-head">
                <span className={`badge ${isLive ? "badge-live" : "badge-demo"}`}>
                  {h.account.account_type.toUpperCase()}
                </span>
                <span className="engine-label">{h.account.label}</span>
              </div>

              <div className="tile-value">
                <span className={`dot ${status.dot}`} aria-hidden="true" />
                {status.label}
              </div>
              <div className="tile-sub">{status.sub}</div>

              {isLive && (
                <p className="engine-note">
                  Live order execution is disabled: risk-based position sizing is not implemented
                  yet. No real order can be placed regardless of readiness or toggles.
                </p>
              )}

              {h.heartbeat ? (
                <div className="engine-controls">
                  <Controls
                    session={session}
                    accountKey={h.account.key}
                    accountLabel={h.account.label}
                  />
                </div>
              ) : (
                <p className="engine-note muted">
                  Controls appear once this account's engine is running.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
