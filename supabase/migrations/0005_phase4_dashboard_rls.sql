-- Phase 4: read-only public monitoring + auth-gated control channel.
--
-- Security model: the dashboard is a static SPA using the Supabase anon key,
-- so RLS is the real boundary, not key secrecy. anon gets narrow SELECT-only
-- access to monitoring data; anything that changes engine behavior requires
-- being signed in (authenticated role) and goes through the `commands` table.

create table if not exists public.commands (
    id bigint generated always as identity primary key,
    command_type text not null check (command_type in ('pause', 'resume', 'emergency_close_all')),
    status text not null default 'pending' check (status in ('pending', 'processed')),
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    processed_at timestamptz
);

create index if not exists commands_status_idx on public.commands (status);

alter table public.commands enable row level security;
grant all on public.commands to service_role;

-- Read-only monitoring, open to anon (no sensitive data - signals/trades on a
-- demo account, engine health). Deliberately no INSERT/UPDATE/DELETE grants.
grant select on public.signals, public.trades, public.engine_heartbeats, public.candles to anon;

create policy "anon read signals" on public.signals for select to anon using (true);
create policy "anon read trades" on public.trades for select to anon using (true);
create policy "anon read heartbeats" on public.engine_heartbeats for select to anon using (true);
create policy "anon read candles" on public.candles for select to anon using (true);

-- Control actions require being signed in. Only insert - no editing/deleting
-- other people's commands, no reading the queue back (engine uses service_role).
grant select, insert on public.commands to authenticated;

create policy "authenticated insert commands" on public.commands
    for insert to authenticated
    with check (auth.uid() = created_by);

create policy "authenticated read own commands" on public.commands
    for select to authenticated
    using (auth.uid() = created_by);
