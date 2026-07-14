-- Strategy Laboratory foundation.
--
-- Turns the single-strategy/single-account system into a registry-driven one
-- that can hold many strategies across many broker accounts, and records the
-- data needed to judge each strategy's edge objectively.
--
-- Design notes (why it looks like this):
--   * accounts + strategies + strategy_accounts are REGISTRIES, not code. Adding
--     a strategy or a broker account is a row, not a schema change - that's what
--     makes this scale to dozens/hundreds without touching migrations again.
--   * Fact tables (trades/signals/heartbeats/commands) carry account_key so
--     every row is attributable to exactly one account. Existing rows default to
--     the demo account, which is factually what they are.
--   * trades gains initial_stop_loss + risk_amount. Trailing-stop management
--     mutates trades.stop_loss, which DESTROYS the original risk distance, so R
--     multiples (the only way to compare EURUSD against XAUUSD fairly) become
--     uncomputable after the fact. These two columns are captured once at open
--     and never updated. Trades opened before this migration have neither and
--     are excluded from R-based statistics by the evaluator.
--   * readiness lives on strategies (one verdict per strategy, always derived
--     from DEMO data - the lab is the judge). strategy_evaluations keeps the
--     snapshot history per (strategy, account) so degradation is visible.
--
-- RLS: enabled everywhere. anon gets nothing (migration 0008 revoked it and the
-- dashboard is behind a login gate). authenticated reads everything and may
-- toggle the manual controls on strategy_accounts only.

-- ---------------------------------------------------------------- accounts --

create table if not exists public.accounts (
    id bigint generated always as identity primary key,
    key text not null unique,          -- stable id the engine puts in .env, e.g. 'icmarkets-demo'
    label text not null,
    broker text not null,              -- plugin key, e.g. 'mt5'
    account_type text not null check (account_type in ('demo', 'live')),
    enabled boolean not null default true,
    created_at timestamptz not null default now()
);

-- -------------------------------------------------------------- strategies --

create table if not exists public.strategies (
    id bigint generated always as identity primary key,
    name text not null unique,         -- must match the plugin key in engine/registry.py
    display_name text,
    description text,
    -- Verdict is computed from demo results by the evaluator, never by hand.
    readiness text not null default 'not_ready'
        check (readiness in ('not_ready', 'almost_ready', 'ready')),
    readiness_reason text,
    readiness_updated_at timestamptz,
    retired boolean not null default false,
    created_at timestamptz not null default now()
);

-- ------------------------------------------------- strategy <-> account map --

-- One row per strategy per account: the manual controls. Separate from
-- `strategies` so enabling a strategy on live never touches its demo life, and
-- so a new account is just N new rows rather than N new columns.
create table if not exists public.strategy_accounts (
    id bigint generated always as identity primary key,
    strategy_name text not null references public.strategies (name) on delete cascade,
    account_key text not null references public.accounts (key) on delete cascade,
    -- Manual on/off. The engine also requires readiness='ready' on live accounts
    -- unless live_override is set - enabled alone is never enough to trade live.
    enabled boolean not null default false,
    live_override boolean not null default false,
    updated_at timestamptz not null default now(),
    unique (strategy_name, account_key)
);

-- ----------------------------------------------------- evaluation snapshots --

create table if not exists public.strategy_evaluations (
    id bigint generated always as identity primary key,
    strategy_name text not null,
    account_key text not null,
    computed_at timestamptz not null default now(),
    trades_count integer not null,
    wins integer not null,
    losses integer not null,
    win_rate double precision,
    expectancy_r double precision,
    ci_low double precision,           -- bootstrap 95% CI on expectancy, in R
    ci_high double precision,
    profit_factor double precision,
    avg_win_r double precision,
    avg_loss_r double precision,
    max_drawdown_r double precision,
    longest_loss_streak integer,
    total_net_pnl double precision,
    verdict text not null check (verdict in ('not_ready', 'almost_ready', 'ready')),
    verdict_reason text
);

-- --------------------------------------------------- account attribution --

alter table public.trades
    add column if not exists account_key text not null default 'icmarkets-demo';
alter table public.signals
    add column if not exists account_key text not null default 'icmarkets-demo';
alter table public.engine_heartbeats
    add column if not exists account_key text not null default 'icmarkets-demo';
alter table public.commands
    add column if not exists account_key text not null default 'icmarkets-demo';

-- ------------------------------------------------------- risk-at-open data --

-- Captured once when the trade opens; never mutated by trailing-stop moves.
alter table public.trades add column if not exists initial_stop_loss double precision;
-- Account-currency amount at risk if the initial stop had been hit. Makes
-- realized R = realized_pnl / risk_amount, exact and instrument-independent.
alter table public.trades add column if not exists risk_amount double precision;

-- ------------------------------------------------------------------ seed --

insert into public.accounts (key, label, broker, account_type)
values ('icmarkets-demo', 'IC Markets Demo (lab)', 'mt5', 'demo')
on conflict (key) do nothing;

insert into public.strategies (name, display_name, description)
values (
    'ema_trend_v1',
    'EMA Trend v1',
    'H4 EMA(50/200) regime + ADX gate, H1 EMA(20/50) crossover entry, ATR stops.'
)
on conflict (name) do nothing;

-- Every known strategy runs on the demo lab by default; live stays off.
insert into public.strategy_accounts (strategy_name, account_key, enabled)
values ('ema_trend_v1', 'icmarkets-demo', true)
on conflict (strategy_name, account_key) do nothing;

-- --------------------------------------------------------------- indexes --

create index if not exists trades_account_key_idx on public.trades (account_key);
create index if not exists trades_strategy_idx on public.trades (strategy_name);
create index if not exists signals_account_key_idx on public.signals (account_key);
create index if not exists heartbeats_account_key_idx on public.engine_heartbeats (account_key);
create index if not exists commands_account_key_idx on public.commands (account_key);
create index if not exists strategy_evaluations_lookup_idx
    on public.strategy_evaluations (strategy_name, account_key, computed_at desc);

-- ------------------------------------------------------------ RLS + grants --

alter table public.accounts enable row level security;
alter table public.strategies enable row level security;
alter table public.strategy_accounts enable row level security;
alter table public.strategy_evaluations enable row level security;

grant all on public.accounts, public.strategies, public.strategy_accounts,
    public.strategy_evaluations to service_role;

-- Read-only for the dashboard...
grant select on public.accounts, public.strategies, public.strategy_accounts,
    public.strategy_evaluations to authenticated;
-- ...except the manual toggles, which the dashboard owns.
grant update (enabled, live_override, updated_at) on public.strategy_accounts to authenticated;

create policy "authenticated read accounts" on public.accounts
    for select to authenticated using (true);
create policy "authenticated read strategies" on public.strategies
    for select to authenticated using (true);
create policy "authenticated read strategy_accounts" on public.strategy_accounts
    for select to authenticated using (true);
create policy "authenticated update strategy_accounts" on public.strategy_accounts
    for update to authenticated using (true) with check (true);
create policy "authenticated read strategy_evaluations" on public.strategy_evaluations
    for select to authenticated using (true);
