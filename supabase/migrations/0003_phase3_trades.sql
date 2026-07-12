-- Phase 3: trade lifecycle (opened -> closed with real P&L). No partial-close
-- support yet (deferred - see PLAN.md). RLS enabled, no policies (deny-all
-- default), same as prior migrations.

create table if not exists public.trades (
    id bigint generated always as identity primary key,
    mt5_ticket text not null unique,
    strategy_name text not null,
    symbol text not null,
    direction text not null,
    lot_size double precision not null,
    entry_price double precision not null,
    stop_loss double precision,
    take_profit double precision,
    status text not null,
    realized_pnl double precision,
    opened_at timestamptz not null,
    closed_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists trades_status_idx on public.trades (status);
create index if not exists trades_symbol_idx on public.trades (symbol);

alter table public.trades enable row level security;

grant all on public.trades to service_role;
