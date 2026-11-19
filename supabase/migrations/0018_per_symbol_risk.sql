-- Per-pair risk for a strategy on an account.
--
-- strategy_accounts.risk_pct (0011) is one number for every pair a strategy
-- trades. This adds optional per-pair overrides, as a JSON object of
-- symbol -> percent, e.g. {"USDCAD": 7, "NZDUSD": 6}. A pair not listed uses
-- risk_pct. NULL (the default) changes nothing.
--
-- engine/gating.py reads it (parse_symbol_risk drops any entry that is not a
-- positive number, so that pair falls back to risk_pct), and
-- engine/plugins/risk/default_risk_engine.py clamps every value to
-- Settings.max_risk_pct - so, as with risk_pct, a bad value can never become
-- an outsized bet.
--
-- Added 2026-11-19 at the owner's request: live london_breakout_v1 risks more
-- on the pairs that have made money live, and 2% on the rest.

alter table public.strategy_accounts
    add column if not exists symbol_risk_pct jsonb
    check (symbol_risk_pct is null or jsonb_typeof(symbol_risk_pct) = 'object');

comment on column public.strategy_accounts.symbol_risk_pct is
    'Per-pair risk percent for this strategy on this account, e.g. {"USDCAD": 7}. Pairs not listed use risk_pct. Clamped by Settings.max_risk_pct at execution time.';

-- The dashboard owns this knob alongside risk_pct.
grant update (symbol_risk_pct) on public.strategy_accounts to authenticated;
