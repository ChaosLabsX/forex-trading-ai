-- How each trade ended, and how far it went for and against us on the way.
--
-- Until now a closed trade recorded only its result. "-$3.91" cannot say
-- whether the entry was wrong (it never went our way) or the exit was (it was
-- +0.8R before reversing) - and those call for opposite fixes. These columns
-- turn "why do we lose?" into something countable. See engine/trade_autopsy.py.
--
--   exit_reason      target | stop | breakeven | trailing_stop | manual | engine |
--                    stop_out | other | unknown - from MT5's own closing deal
--   exit_price       fill of the closing deal
--   max_favorable_r  best price reached while open, in R of the initial risk (>= 0)
--   max_adverse_r    worst price reached while open, in R (<= 0)
--
-- Written by the engine in the SAME update that marks a trade CLOSED, so they
-- cost no extra Supabase requests (the free-plan egress budget, 2026-10). If
-- the engine is deployed before this runs, its close retries without these
-- columns - a trade is never left OPEN for want of them.
--
-- Nullable on purpose: older trades get NULL until
-- scripts/backfill_trade_autopsy.py fills them from MT5's deal history, and
-- anything it can't read stays NULL rather than guessed. realized_pnl remains
-- the source of truth for every statistic; nothing computes a verdict off these.
--
-- Table-level grants on `trades` already cover new columns (service_role
-- writes, authenticated reads) - same as 0014 and 0015.

alter table public.trades
    add column if not exists exit_reason text,
    add column if not exists exit_price double precision,
    add column if not exists max_favorable_r double precision,
    add column if not exists max_adverse_r double precision;
