import type { Session } from "@supabase/supabase-js";
import { useAuth } from "../lib/useAuth";
import { useDashboardData } from "../lib/useDashboardData";
import { StatTiles } from "./StatTiles";
import { PausedBanner } from "./PausedBanner";
import { Engines } from "./Engines";
import { StrategyLab } from "./StrategyLab";
import { OpenTrades } from "./OpenTrades";
import { TradeHistory } from "./TradeHistory";
import { SignalsFeed } from "./SignalsFeed";
import { SetPassword } from "./SetPassword";

const logoUrl = `${import.meta.env.BASE_URL}pwa-192x192.png`;

export function Dashboard({ session }: { session: Session }) {
  const { signOut } = useAuth();
  const { health, openTrades, closedTrades, signals, loading } = useDashboardData();

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
          <PausedBanner session={session} paused={health.filter((h) => h.paused)} />
          <StatTiles health={health} openTrades={openTrades} closedTrades={closedTrades} />
          <StrategyLab />
          <Engines session={session} health={health} />
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
