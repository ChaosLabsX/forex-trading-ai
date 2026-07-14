import { useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { useAuth } from "../lib/useAuth";
import { useDashboardData } from "../lib/useDashboardData";
import { StatTiles } from "./StatTiles";
import { PausedBanner } from "./PausedBanner";
import { AccountFilter } from "./AccountFilter";
import { Engines } from "./Engines";
import { StrategyLab } from "./StrategyLab";
import { OpenTrades } from "./OpenTrades";
import { TradeHistory } from "./TradeHistory";
import { SignalsFeed } from "./SignalsFeed";
import { SetPassword } from "./SetPassword";

const logoUrl = `${import.meta.env.BASE_URL}pwa-192x192.png`;

export function Dashboard({ session }: { session: Session }) {
  const { signOut } = useAuth();
  const { accounts, health, openTrades, closedTrades, signals, loading } = useDashboardData();
  const [selected, setSelected] = useState<string | null>(null);

  // Default to the live account once it's actually in service - that's the one
  // that matters when real money is on the line. Falls back to the demo lab.
  const activeKey = useMemo(() => {
    if (selected) return selected;
    const live = accounts.find((a) => a.account_type === "live" && a.enabled);
    return live?.key ?? accounts[0]?.key ?? null;
  }, [selected, accounts]);

  // Everything money-related is scoped to ONE account. Mixing demo and live
  // P&L would produce a meaningless total.
  const scoped = useMemo(
    () => ({
      health: health.filter((h) => h.account.key === activeKey),
      open: openTrades.filter((t) => t.account_key === activeKey),
      closed: closedTrades.filter((t) => t.account_key === activeKey),
      signals: signals.filter((s) => s.account_key === activeKey),
    }),
    [health, openTrades, closedTrades, signals, activeKey]
  );

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
          {/* Pause is engine state, not account scope - never hide it behind a filter. */}
          <PausedBanner session={session} paused={health.filter((h) => h.paused)} />
          <AccountFilter accounts={accounts} selected={activeKey} onSelect={setSelected} />
          <StatTiles health={scoped.health} openTrades={scoped.open} closedTrades={scoped.closed} />
          <StrategyLab />
          <Engines session={session} health={health} />
          <OpenTrades trades={scoped.open} />
          <TradeHistory trades={scoped.closed} />
          <SignalsFeed signals={scoped.signals} />
          <details className="account">
            <summary>Account settings</summary>
            <SetPassword />
          </details>
        </>
      )}
    </div>
  );
}
