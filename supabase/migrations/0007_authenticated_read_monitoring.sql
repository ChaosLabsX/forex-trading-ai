-- Fix: signed-in users got 403 on the monitoring tables. supabase-js sends
-- the user's authenticated JWT once signed in (not the anon key), and
-- `authenticated` had no grants at all on these tables - anon-only was an
-- oversight, since a signed-in user should see at least what anon can see.

grant select on public.signals, public.trades, public.engine_heartbeats, public.candles, public.ai_reviews
    to authenticated;

create policy "authenticated read signals" on public.signals for select to authenticated using (true);
create policy "authenticated read trades" on public.trades for select to authenticated using (true);
create policy "authenticated read heartbeats" on public.engine_heartbeats for select to authenticated using (true);
create policy "authenticated read candles" on public.candles for select to authenticated using (true);
create policy "authenticated read ai_reviews" on public.ai_reviews for select to authenticated using (true);
