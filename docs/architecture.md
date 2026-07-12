# Architecture overview

See [`PLAN.md`](../APP-CREATION-PLANNING.md) for the phased roadmap and the
reasoning behind each major decision. This doc is the current-state map.

## Hard constraint

MT5 has no public REST API. The official `MetaTrader5` Python package requires a
locally running, logged-in MT5 terminal and is Windows-only, with no push/callback
model - "tick-driven" means a tight sub-second polling loop. The engine is a
persistent process on a Windows VPS with MT5 open and logged into IC Markets 24/7.

## Layout

```
engine/            Python package - runs as a Windows service on the VPS
  core/
    models.py       shared data types (Candle, Signal, Position, ...)
    interfaces/      one abstract contract per subsystem (see plugin-system.md)
  plugins/           concrete implementations of those contracts
  config.py          Settings (secrets, from .env) + PluginConfig (from config/plugins.yaml)
  registry.py        config-driven composition root - wires plugins together
dashboard/          React + TypeScript SPA - GitHub Pages, Supabase JS client
docs/                one doc per subsystem + this overview
infra/               VPS/service setup guidance (not executed by Claude)
config/plugins.yaml  which plugin backs each subsystem (not secret, committed)
```

## Data flow (current, as of Phase 4)

1. `MarketDataProvider` (MT5) feeds candles to the engine loop every 60s;
   `BrokerAdapter` (MT5) provides account state/open positions.
2. Each configured `StrategyPlugin` evaluates the current context (once per
   newly-closed bar, deduplicated) and may return a `Signal`.
3. `RiskEngine` validates the signal against account state and safety rails
   (`TEST_MODE`, max concurrent trades, circuit breakers driven by real MT5
   deal history) -> `RiskDecision`.
4. `ExecutionEngine` turns an approved decision into orders via `BrokerAdapter`.
   Breakeven/trailing management is not implemented yet (v1 relies on MT5's
   native SL/TP enforcement).
5. Every lifecycle event (signal fired/filtered, trade opened/closed with real
   P&L) is persisted to Supabase and pushed through `NotificationProvider`
   (Telegram).
6. The dashboard reads Supabase directly (RLS-scoped, anon key, polled client-side
   every ~15s) and writes manual commands (pause, resume, emergency-close-all)
   to a `commands` table. The engine polls that table on its existing 2-second
   tick - not a Supabase Realtime subscription as originally planned; polling on
   an already-existing tick was simpler with no meaningful latency cost here.
7. Optionally, `AIProvider` (Claude, Phase 5 - not yet built) will review a
   signal before step 4.

Currently runs locally on a Windows dev machine (MT5 terminal + Python engine
side by side); VPS deployment is Phase 6.

## Security model

- Dashboard is a static SPA (GitHub Pages) using the Supabase **anon** key -
  Row-Level Security policies are the real access boundary, not key secrecy.
- The Supabase **service-role** key, MT5 credentials, Telegram bot token, and
  Anthropic API key live only in the VPS process's `.env` (gitignored).
- `TEST_MODE` (see `.env.example`) gates sizing/thresholds; defaults to `true`.
