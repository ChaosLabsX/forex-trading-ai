-- Register the real IC Markets account so the live half of the architecture
-- exists end-to-end (dashboard, gating, evaluation, reporting) before a single
-- real order is possible.
--
-- Seeded `enabled = false` deliberately. That means:
--   * it appears on the dashboard and in reports as a known account,
--   * the daily digest does NOT warn that its engine is missing (there isn't
--     one yet - nothing is expected to heartbeat for it),
--   * and even if an engine were pointed at it, engine/gating.py blocks every
--     strategy account-wide while LIVE_SIZING_IMPLEMENTED is False.
-- Three independent guards, all pointing the same way: no live order can be
-- placed until risk-based position sizing is built and this row is enabled.
--
-- Strategies are linked to it with enabled = false, so promoting a strategy to
-- READY still does not silently start trading it live - that stays a
-- deliberate, manual switch.

insert into public.accounts (key, label, broker, account_type, enabled)
values ('icmarkets-live', 'IC Markets Live (production)', 'mt5', 'live', false)
on conflict (key) do nothing;

insert into public.strategy_accounts (strategy_name, account_key, enabled)
select s.name, 'icmarkets-live', false
from public.strategies s
on conflict (strategy_name, account_key) do nothing;
