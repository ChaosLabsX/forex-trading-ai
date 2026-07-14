-- Per-(strategy, account) risk allocation.
--
-- This is the ONLY sizing input that legitimately varies per strategy. Lot
-- min/max/step and margin are the broker's contract specs, read live from MT5 at
-- runtime (never hardcoded, or they silently rot when the broker changes them),
-- and the sizing maths itself is one shared, tested function.
--
-- NULL means "use Settings.default_risk_pct". A value here can lower risk for a
-- strategy, but engine/plugins/risk/default_risk_engine.py clamps it to
-- Settings.max_risk_pct, so a bad row can never become an outsized bet.
--
-- It lives on strategy_accounts (not strategies) so the same strategy can run at
-- a different risk on the live account than in the demo lab - which is exactly
-- what you want when first trusting one with real money.

alter table public.strategy_accounts
    add column if not exists risk_pct double precision
    check (risk_pct is null or (risk_pct > 0 and risk_pct <= 10));

comment on column public.strategy_accounts.risk_pct is
    'Percent of equity to risk per trade for this strategy on this account. NULL = use the engine default. Clamped by Settings.max_risk_pct at execution time.';

-- The dashboard owns this knob alongside the other manual controls.
grant update (risk_pct) on public.strategy_accounts to authenticated;
