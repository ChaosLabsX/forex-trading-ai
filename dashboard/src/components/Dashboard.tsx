import type { Session } from "@supabase/supabase-js";
import { useAuth } from "../lib/useAuth";
import { useDashboardData } from "../lib/useDashboardData";
import { StatTiles } from "./StatTiles";
import { PausedBanner } from "./PausedBanner";
import { StrategyLab } from "./StrategyLab";
import { Controls } from "./Controls";
import { OpenTrades } from "./OpenTrades";
import { TradeHistory } from "./TradeHistory";
import { SignalsFeed } from "./SignalsFeed";
import { SetPassword } from "./SetPassword";

const logoUrl = `${import.meta.env.BASE_URL}pwa-192x192.png`;
const STALE_AFTER_MS = 3 * 60 * 1000; // must match StatTiles' liveness window

export function Dashboard({ session }: { session: Session }) {
  const { signOut } = useAuth();
  const { heartbeat, openTrades, closedTrades, signals, loading } = useDashboardData();

  // Only trust a "paused" status from a recent heartbeat - a stale one tells us
  // nothing about the engine's current state.
  const heartbeatFresh =
    heartbeat !== null && Date.now() - new Date(heartbeat.created_at).getTime() <= STALE_AFTER_MS;
  const paused = heartbeatFresh && heartbeat?.status === "paused";

  return (
    <div className="shell">
      <header className="topbar">
        <img src={logoUrl} className="topbar-logo" alt="" />
        <h1 className="topbar-title">Forex AI</h1>
        <span className="topbar-spacer" />
        <button
          className="btn btn-ghost"
          onClick={() => signOut()}
          title={session.user.email ?? undefined}
        >
          Sign out
        </button>
      </header>

      {loading ? (
        <div className="gate">
          <div className="spinner" aria-label="Loading" />
        </div>
      ) : (
        <>
          {paused && <PausedBanner session={session} />}
          <StatTiles heartbeat={heartbeat} openTrades={openTrades} closedTrades={closedTrades} />
          <StrategyLab />
          <Controls session={session} />
          <OpenTrades trades={openTrades} />
          <TradeHistory trades={closedTrades} />
          <SignalsFeed signals={signals} />
          <details className="account">
            <summary>Account settings</summary>
            <SetPassword />
          </details>
        </>
      )}
    </div>
  );
}
