import type { Session } from "@supabase/supabase-js";
import type { AccountHealth } from "../lib/useDashboardData";
import { fmtAgo } from "../lib/format";
import { Controls } from "./Controls";

type Props = { session: Session; health: AccountHealth[] };

/** Contract with the engine: `_live_trading_detail()` in engine/loop.py puts
 * one of these in the heartbeat's `detail` for LIVE accounts only. Anything
 * else - including NULL from an engine that predates it - means "unknown", and
 * is rendered as unknown rather than assumed either way. */
const LIVE_TRADING_ON = "live_trading=on";
const LIVE_TRADING_OFF = "live_trading=off";

/** Guard 1 (LIVE_TRADING_ENABLED) is an environment variable on the VPS, not a
 * database row, so the only way the dashboard learns it is the engine saying
 * so - and only a CURRENT heartbeat can be trusted for it. A stale one
 * describes a process that may no longer be running, or may have been restarted
 * with a different .env since. */
function liveTradingState(h: AccountHealth): "on" | "off" | "unknown" {
  if (!h.online) return "unknown";
  if (h.heartbeat?.detail === LIVE_TRADING_ON) return "on";
  if (h.heartbeat?.detail === LIVE_TRADING_OFF) return "off";
  return "unknown";
}

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

              {/* This used to be a hardcoded "live execution is disabled, sizing
                  isn't implemented" note. Sizing landed, the account was funded,
                  and the sentence stayed - so the dashboard was telling you no
                  real order could be placed while the engine was armed to place
                  one. Never state a guard's position from a constant; read it
                  from the thing that enforces it. */}
              {isLive && <LiveTradingNote state={liveTradingState(h)} />}

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

/** What guard 1 is doing right now, in the account card that guard applies to.
 *
 * Deliberately says only what it can see. Whether a real order actually gets
 * placed also needs the account enabled, the strategy enabled on it, and either
 * a READY verdict or a live_override - all of which live in the lab table
 * below, where they can be toggled. This note is about the master switch. */
function LiveTradingNote({ state }: { state: "on" | "off" | "unknown" }) {
  if (state === "on") {
    return (
      <p className="engine-note">
        <strong>Real orders are armed.</strong> This engine can place trades with real money.
        Which strategies may do so is set per-strategy in the lab below.
      </p>
    );
  }
  if (state === "off") {
    return (
      <p className="engine-note muted">
        Live trading is off (<code>LIVE_TRADING_ENABLED</code>). No real order can be placed,
        whatever the readiness verdict or the per-strategy toggles say.
      </p>
    );
  }
  return (
    <p className="engine-note muted">
      Live trading state unknown - the engine has not reported it. It is published on each
      heartbeat, so this resolves as soon as a current engine checks in.
    </p>
  );
}
