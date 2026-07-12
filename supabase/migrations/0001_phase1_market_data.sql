-- Phase 1: raw candle persistence + engine health heartbeat.
-- RLS is enabled with no policies, so anon/authenticated get zero access by
-- default (service_role bypasses RLS entirely) - safe even before the
-- dashboard/RLS policies exist.

create table if not exists public.candles (
    id bigint generated always as identity primary key,
    symbol text not null,
    timeframe text not null,
    time timestamptz not null,
    open double precision not null,
    high double precision not null,
    low double precision not null,
    close double precision not null,
    volume double precision not null,
    inserted_at timestamptz not null default now(),
    unique (symbol, timeframe, time)
);

create index if not exists candles_symbol_timeframe_time_idx
    on public.candles (symbol, timeframe, time desc);

alter table public.candles enable row level security;

create table if not exists public.engine_heartbeats (
    id bigint generated always as identity primary key,
    status text not null,
    broker_connected boolean not null,
    detail text,
    created_at timestamptz not null default now()
);

create index if not exists engine_heartbeats_created_at_idx
    on public.engine_heartbeats (created_at desc);

alter table public.engine_heartbeats enable row level security;

-- service_role should bypass RLS by default, but grants on these specific
-- tables/sequences weren't applied automatically on this project - make them
-- explicit, and set the default going forward so future tables don't need this.
grant usage on schema public to service_role;
grant all on public.candles, public.engine_heartbeats to service_role;
grant usage, select on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant usage, select on sequences to service_role;

