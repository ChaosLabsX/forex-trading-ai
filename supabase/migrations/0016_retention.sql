-- Keep the database inside the Supabase free plan, for good.
--
-- On 2026-10-12 Supabase warned the organization was over quota and that
-- projects would be restricted from 2026-10-25. A restricted project stops
-- answering the engine, and an engine that can't read its registries refuses
-- to trade (gating.py: "refusing to trade blind") - safe, but nothing trades.
--
-- What filled it was never trading data. Row counts that day:
--   candles             675,361  mostly duplicates of the same bars (see the
--                                one-time cleanup below); a copy of history
--                                MT5 already keeps (the backtest reads it there)
--   engine_heartbeats   170,284  one per engine per minute since July; only the
--                                latest per account is ever read
--   signals             106,444  every evaluation, fired or not; 105,080 did
--                                not fire
--   strategy_evaluations 53,986  a snapshot per strategy x account every 30 min
--   trades                  902  <- the data that matters
--   ai_reviews              216
--
-- prune_old_rows() trims the four big tables and runs daily via pg_cron. It
-- never touches trades, ai_reviews, accounts, strategies, strategy_accounts or
-- commands, and keeps every row anything reads:
--
--   engine_heartbeats    7 days. Dashboard, watchdog.ps1, the daily summary
--                        and check_engine_health.py all read the latest only.
--   signals              60 days of evaluations that did NOT fire. Fired
--                        signals are kept forever: trades.signal_id points at
--                        them (0014, ON DELETE SET NULL - deleting one would cut
--                        a trade off from its AI review) and ai_reviews.signal_id
--                        too (0006, ON DELETE CASCADE - deleting one would delete
--                        the review). The NOT EXISTS clauses guard both even if
--                        a non-fired row were ever linked.
--   strategy_evaluations 30 days, and never the newest row per (strategy,
--                        account) - that row is what the dashboard shows.
--   candles              180 days - longer than every engine window (D1 is 90
--                        bars, about four months).
--
-- Deleting frees space for reuse but does not shrink what Supabase reports as
-- database size. After the first run, VACUUM FULL each table once (see the end
-- of this file); later daily runs only keep the size flat.

create extension if not exists pg_cron;

create or replace function public.prune_old_rows()
returns table (table_name text, deleted bigint)
language plpgsql
security definer
set search_path = public
as $$
declare
    n bigint;
begin
    delete from public.engine_heartbeats
     where created_at < now() - interval '7 days';
    get diagnostics n = row_count;
    table_name := 'engine_heartbeats'; deleted := n; return next;

    delete from public.signals s
     where s.fired = false
       and s.created_at < now() - interval '60 days'
       and not exists (select 1 from public.trades t where t.signal_id = s.id)
       and not exists (select 1 from public.ai_reviews r where r.signal_id = s.id);
    get diagnostics n = row_count;
    table_name := 'signals (not fired)'; deleted := n; return next;

    delete from public.strategy_evaluations e
     where e.computed_at < now() - interval '30 days'
       and e.id not in (
           select distinct on (strategy_name, account_key) id
             from public.strategy_evaluations
            order by strategy_name, account_key, computed_at desc
       );
    get diagnostics n = row_count;
    table_name := 'strategy_evaluations'; deleted := n; return next;

    delete from public.candles
     where time < now() - interval '180 days';
    get diagnostics n = row_count;
    table_name := 'candles'; deleted := n; return next;
end;
$$;

-- security definer bypasses RLS, so nobody but the owner may call it. Without
-- this, PostgREST would expose it as /rpc/prune_old_rows to the anon key.
revoke all on function public.prune_old_rows() from public, anon, authenticated;

-- Daily at 21:30 UTC: after the 21:00 daily summary, far from the London open.
-- Scheduling an existing job name replaces it, so re-running this is harmless.
select cron.schedule('prune-old-rows', '30 21 * * *', $$select public.prune_old_rows()$$);

-- ONE-TIME: the shifted duplicate candles. Most of the 675,361 rows were not
-- history at all but copies of the same bar under slightly different
-- timestamps (09:00:00.31, 09:00:01.08, 08:56:27 ...). Before the clock fixes
-- the broker's UTC offset was re-measured on every restart, a little
-- differently each time, and each restart re-sent the whole window - so the
-- (symbol, timeframe, time) unique key never matched and every restart added
-- rows. EURUSD H1 held 17,497 rows for 2,094 real bars, and 519 of those bars
-- had copies disagreeing on price (a still-forming bar saved mid-way and never
-- updated, because the next save landed under another timestamp).
--
-- Every bar of the engine's timeframes (H1/H4/D1) opens exactly on an hour, and
-- every row saved since 2026-09-20 does. So anything off the hour is a broken
-- copy. Nothing reads this table to trade - it is an archive, and MT5 keeps the
-- real history. Restricted to H1/H4/D1 so a finer timeframe added later (M15
-- bars open at :15) can never be caught by it.
delete from public.candles
 where timeframe in ('H1', 'H4', 'D1')
   and time <> date_trunc('hour', time);

-- First run of the daily trim, now - prints how many rows each table lost:
select * from public.prune_old_rows();

-- Then, ONE AT A TIME (VACUUM can't share a run with other statements), to hand
-- the freed space back so the reported size drops. Each locks its table for a
-- few seconds; the engine's writes wait and carry on:
--   vacuum full public.candles;
--   vacuum full public.signals;
--   vacuum full public.engine_heartbeats;
--   vacuum full public.strategy_evaluations;
