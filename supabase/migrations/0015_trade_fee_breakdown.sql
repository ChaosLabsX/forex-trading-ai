-- Persist the fee split that the engine already computes and then throws away.
--
-- `get_closed_position_breakdown()` returns ClosedTradePnl(gross_profit,
-- commission, swap) - built by summing across ALL of a position's deals,
-- because commission is charged on entry AND exit. The loop used `.net` and
-- discarded the parts, so Telegram could report a win before fees (the house
-- grammar in engine/reporting.py) but the dashboard could not: it only ever had
-- one number and no way to tell a $2 win with $2 of costs from a clean one.
--
-- Storing the three components rather than a single `fees` column keeps the
-- broker's own signed values intact (commission is normally negative, swap can
-- be either) and lets net be re-derived instead of trusted:
--   realized_pnl == gross_profit + commission + swap
--
-- realized_pnl STAYS the source of truth for every statistic - expectancy, R
-- multiples, the readiness verdict, the AI review scoring. These columns are
-- presentation detail, deliberately additive, and nothing computes off them.
--
-- Nullable on purpose: every trade closed before this migration keeps NULL, and
-- the dashboard treats NULL as "fees unknown" and falls back to showing net,
-- rather than inventing a gross figure from a number that already had fees
-- deducted. Backfilling is not possible from Supabase - the split lives in the
-- MT5 terminal's deal history, not here.
--
-- Table-level grants on `trades` already cover new columns (service_role
-- writes, authenticated reads), so no new grant is needed - same as 0014.

alter table public.trades
    add column if not exists gross_profit double precision,
    add column if not exists commission double precision,
    add column if not exists swap double precision;

comment on column public.trades.gross_profit is
    'Market P&L before any costs, summed across the position''s deals. NULL for trades closed before migration 0015. realized_pnl = gross_profit + commission + swap.';

comment on column public.trades.commission is
    'Broker commission, entry + exit deals, in the broker''s own sign convention (normally negative). NULL before migration 0015.';

comment on column public.trades.swap is
    'Overnight financing, signed - can be positive or negative. NULL before migration 0015.';
