-- The dashboard now shows nothing without signing in (full login gate).
-- Hiding the UI alone would be cosmetic - the data would remain publicly
-- queryable via the REST API with the anon key. Revoke anon's read access so
-- the gate is enforced at the database. The auth endpoints themselves still
-- work with the anon key (unaffected by table grants), and signed-in users
-- keep the `authenticated` grants/policies from migration 0007.

revoke select on public.signals, public.trades, public.engine_heartbeats, public.candles, public.ai_reviews
    from anon;

drop policy if exists "anon read signals" on public.signals;
drop policy if exists "anon read trades" on public.trades;
drop policy if exists "anon read heartbeats" on public.engine_heartbeats;
drop policy if exists "anon read candles" on public.candles;
drop policy if exists "anon read ai_reviews" on public.ai_reviews;
