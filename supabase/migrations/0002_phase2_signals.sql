-- Phase 2: every strategy evaluation gets logged, fired or filtered, with why.
-- RLS enabled with no policies (deny-all by default), same as 0001.

create table if not exists public.signals (
    id bigint generated always as identity primary key,
    strategy_name text not null,
    symbol text not null,
    fired boolean not null,
    direction text,
    timeframe text,
    entry_price double precision,
    stop_loss double precision,
    take_profit double precision,
    reason text not null,
    metadata jsonb,
    created_at timestamptz not null default now()
);

create index if not exists signals_created_at_idx on public.signals (created_at desc);
create index if not exists signals_symbol_fired_idx on public.signals (symbol, fired);

alter table public.signals enable row level security;

grant all on public.signals to service_role;
