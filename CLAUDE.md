# CLAUDE.md

Orientation for AI coding assistants (and humans) working in this repo. Read
this first; it links to everything else.

## What this is

A strategy-agnostic automated trading system for MetaTrader 5 via IC Markets:
a Python engine that watches the market and (on the demo account, gated by
`TEST_MODE`) places trades, plus a React dashboard for monitoring and manual
control. Personal use, not a SaaS product. Independent of any other project -
no shared code, credentials, or infra with anything else.

## Hard constraint - read this before proposing anything MT5-related

MT5 has no public REST API. The official `MetaTrader5` Python package only
works by talking to a **locally running, logged-in MT5 terminal**, and is
**Windows-only**. It's a synchronous IPC bridge with no push/callback model -
polling is the only option, not true event push. There is no serverless or
cross-platform version of the execution side; don't suggest one.

## Current status (check before assuming what's built)

All 8 subsystem interfaces have a working plugin. Phases 0-5 of
[`APP-CREATION-PLANNING.md`](APP-CREATION-PLANNING.md) are built; Phase 6 (VPS
deployment) is intentionally not started. That file's "Status" line at the very
bottom is the single source of truth for what's currently running vs. pending -
check it before assuming something is or isn't done. Don't trust this file's
prose to stay perfectly in sync; if in doubt, read the code.

Everything currently runs on a local Windows dev machine (MT5 terminal + the
Python engine side by side), not a VPS.

## Architecture in one paragraph

`engine/` is a Python package with 8 abstract interfaces
(`engine/core/interfaces/`) and a config-driven plugin registry
(`engine/registry.py` + `config/plugins.yaml`) - core code never imports a
concrete plugin directly. `engine/loop.py` is the actual running process:
connect to MT5 → refresh candles → evaluate strategies → risk-check → execute
→ track lifecycle → reconcile closures → review with AI (shadow mode) → poll
for dashboard commands, on a repeating tick. Every meaningful event is
persisted to Supabase (Postgres); `dashboard/` is a React SPA that reads
Supabase directly (anon key, RLS-scoped) and writes manual commands
(pause/resume/emergency-close) that the engine picks up. See
[`docs/architecture.md`](docs/architecture.md) for the full data flow and
[`docs/plugin-system.md`](docs/plugin-system.md) for how to add a new
broker/strategy/provider without touching anything else.

## Docs map

| Doc | Read for |
|---|---|
| [`APP-CREATION-PLANNING.md`](APP-CREATION-PLANNING.md) | phased roadmap, current status, the reasoning behind every major decision (and corrections made along the way) |
| [`docs/architecture.md`](docs/architecture.md) | system layout, data flow, security model |
| [`docs/plugin-system.md`](docs/plugin-system.md) | the interface/plugin pattern, how to extend it |
| [`docs/engine.md`](docs/engine.md) | the Python engine in depth - loop mechanics, each plugin's actual behavior |
| [`docs/dashboard.md`](docs/dashboard.md) | the React dashboard in depth - structure, auth model, how to add a view |
| [`docs/safety-rails.md`](docs/safety-rails.md) | `TEST_MODE`, circuit breakers, the RLS security model, known gaps |
| [`infra/vps-setup.md`](infra/vps-setup.md) | VPS provisioning guidance for Phase 6 (not executed yet) |

## Conventions specific to this repo

- **Every plugin class takes exactly one constructor argument: `settings: Settings`.** Anything a plugin needs beyond that comes in as a method parameter (e.g. `ExecutionEngine.execute(order, broker)` takes the broker explicitly rather than holding one).
- **Secrets live in `.env` (root, for the engine) and `dashboard/.env` (for the dashboard's build-time Supabase URL/anon key) - both gitignored.** `config/plugins.yaml` is not secret and is committed; it only names which plugin backs each subsystem.
- **Migrations in `supabase/migrations/` are numbered and additive - never edit an already-applied one.** They're applied directly via the Supabase Management API (no `supabase` CLI is in use); each file's own header comment says what it does and why.
- **RLS is the dashboard's real security boundary, not the anon key.** Every table the dashboard reads needs explicit grants + policies for *both* `anon` and `authenticated` roles if signed-in users need to see it too - a real bug here (403s for signed-in users) came from granting `anon` only. See `docs/safety-rails.md`.
- **Indicators (`engine/indicators.py`) are hand-rolled, not a TA library dependency** - EMA/ATR/ADX, small and dependency-free on purpose.
- **`StrategyPlugin.evaluate()` returns `StrategyEvaluation(signal, reason)`, not a bare `Signal | None`** - every evaluation gets logged with why, fired or not.
- Windows-only project: use PowerShell conventions, backslash paths are fine, and don't suggest Docker/Linux-only tooling for anything that touches MT5.

## Running things locally

```
# engine (from repo root, venv active)
pip install -e .
cp .env.example .env            # fill in as needed - see docs/safety-rails.md for what's optional
python scripts/smoke_test_registry.py   # sanity-check the plugin registry, no external calls needed
python scripts/run_engine.py            # the actual persistent loop (needs MT5 terminal open + logged in)
python scripts/backtest_ema_trend_v1.py # sanity-check the reference strategy against history

# dashboard (from dashboard/)
npm install
cp .env.example .env             # VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm run dev
```
