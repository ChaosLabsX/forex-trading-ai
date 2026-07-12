# Architecture overview

See [`PLAN.md`](../APP-CREATION-PLANNING.md) for the phased roadmap and the
reasoning behind each major decision. This doc is the current-state map.

## Hard constraint

MT5 has no public REST API. The official `MetaTrader5` Python package requires a
locally running, logged-in MT5 terminal and is Windows-only, with no push/callback
model - "tick-driven" means a tight sub-second polling loop. The engine is a
persistent process on a Windows machine with MT5 open and logged into IC Markets
24/7 - a local dev machine today, a VPS once Phase 6 happens.

## Layout

```
engine/            Python package - the persistent trading engine
  core/
    models.py       shared data types (Candle, Signal, Position, ...)
    interfaces/      one abstract contract per subsystem (see plugin-system.md)
  plugins/           concrete implementations of those contracts
  config.py          Settings (secrets, from .env) + PluginConfig (from config/plugins.yaml)
  registry.py        config-driven composition root - wires plugins together
  loop.py            the actual running process - see docs/engine.md
  indicators.py       EMA/ATR/ADX, hand-rolled
  supabase_client.py  minimal PostgREST wrapper (insert/upsert/select/update)
dashboard/          React + TypeScript SPA - GitHub Pages, Supabase JS client
docs/                one doc per subsystem + this overview
infra/               VPS/service setup guidance (Phase 6, not executed yet)
scripts/             entrypoints: run_engine.py, backtest_ema_trend_v1.py, smoke_test_registry.py
supabase/migrations/ numbered, additive SQL migrations - source of truth for DB schema/RLS
config/plugins.yaml  which plugin backs each subsystem (not secret, committed)
```

## Data flow (current, Phases 0-5 all built)

1. `MarketDataProvider` (MT5) feeds candles to the engine loop every 60s;
   `BrokerAdapter` (MT5) provides account state/open positions.
2. Each configured `StrategyPlugin` evaluates the current context (once per
   newly-closed bar, deduplicated) and returns a `StrategyEvaluation` - a
   `Signal` if it fired, plus a reason either way.
3. `RiskEngine` validates a fired signal against account state and safety rails
   (`TEST_MODE` fixed-lot sizing, max concurrent trades, circuit breakers driven
   by real MT5 deal history) -> `RiskDecision`.
4. `ExecutionEngine` turns an approved decision into orders via `BrokerAdapter`.
   Breakeven/trailing management is not implemented yet (v1 relies on MT5's
   native SL/TP enforcement).
5. `AIProvider` (Claude) reviews the same fired signal in **shadow mode** -
   logged for later comparison, never gates execution.
6. Every lifecycle event (signal fired/filtered, risk decision, AI verdict,
   trade opened/closed with real P&L) is persisted to Supabase and pushed
   through `NotificationProvider` (Telegram).
7. The dashboard reads Supabase directly (RLS-scoped, anon key, polled
   client-side every ~15s) and writes manual commands (pause, resume,
   emergency-close-all) to a `commands` table. The engine polls that table on
   its existing 2-second tick - not a Supabase Realtime subscription as
   originally planned; polling on an already-existing tick was simpler with no
   meaningful latency cost here.

Currently runs locally on a Windows dev machine (MT5 terminal + Python engine
side by side, engine launched as a detached background process); VPS
deployment is Phase 6, not started.

## Security model

- Dashboard is a static SPA (GitHub Pages) using the Supabase **anon** key -
  Row-Level Security policies are the real access boundary, not key secrecy.
- Monitoring tables (`signals`, `trades`, `engine_heartbeats`, `candles`,
  `ai_reviews`) grant `SELECT` to **both** `anon` and `authenticated` - a real
  bug shipped here once (anon-only), causing signed-in users to get 403s,
  since `supabase-js` sends the user's session JWT once signed in, not the
  anon key. See `docs/safety-rails.md`.
- The `commands` table only grants `INSERT`/`SELECT` to `authenticated`,
  checked against `auth.uid() = created_by` - control actions require signing
  in. Public sign-up is disabled on the Supabase Auth project; only one
  invited user exists.
- The Supabase **service-role** key, MT5 credentials, Telegram bot token, and
  Anthropic API key live only in the engine process's `.env` (gitignored, on
  whatever machine runs the engine - currently the local dev machine).
- `TEST_MODE` (see `.env.example`) gates sizing/thresholds; defaults to `true`.
