# CLAUDE.md

Orientation for AI coding assistants (and humans) working in this repo. Read
this first; it links to everything else.

## What this is

A **quantitative research platform** that happens to be able to trade. A Python
engine runs 24/7 on a VPS against MetaTrader 5 / IC Markets, runs candidate
strategies on a demo account, and grades each one statistically. A React
dashboard monitors it. Personal use, not a SaaS product.

The point is not "a bot that trades". The point is **deciding, on evidence,
whether any strategy deserves real money** - and refusing when it doesn't. That
refusal is the product.

## Current status (read before assuming anything)

- **Engine: live 24/7** on the VPS (`162.220.166.12`) via Task Scheduler +
  auto-login. Survives reboots unattended (verified).
- **6 strategies** run in the demo lab across 16-25 instruments.
- **No demonstrated edge. Nothing is READY.** ~37,000 simulated trades across
  5 mechanisms and up to 12.7 years of history. See
  [`docs/research-log.md`](docs/research-log.md) - **read it before proposing a
  strategy.**
- **Live trading is off behind four independent guards.** The live account is
  registered, funded with $0, and cannot place an order. See
  [`docs/going-live.md`](docs/going-live.md).
- **The user's plan:** wait for a `🏆 READY` Telegram alert, then fund the live
  account and enable that one strategy. Nothing else is pending.

## Hard constraint - read before proposing anything MT5-related

MT5 has no public REST API. The official `MetaTrader5` Python package only works
by talking to a **locally running, logged-in MT5 terminal**, and is
**Windows-only**. It is a synchronous IPC bridge with no push/callback model -
polling is the only option. There is no serverless or cross-platform version of
the execution side; don't suggest one. (A different *broker* - IBKR, Tradovate -
would remove this, and the `BrokerAdapter` interface exists so that is a plugin,
not a rewrite. See the research log for why that is a real but premature move.)

## Architecture in one paragraph

`engine/` is a Python package with 8 abstract interfaces
(`engine/core/interfaces/`) and a config-driven plugin registry
(`engine/registry.py` + `config/plugins.yaml`) - core code never imports a
concrete plugin. `engine/loop.py` is the running process: connect → refresh
candles → evaluate each strategy against **its own** positions → risk-check →
execute → manage stops → reconcile closures → AI review (shadow) → grade
strategies → poll for dashboard commands. Behaviour is driven at runtime by
**registries in Supabase** (accounts, strategies, strategy_accounts), so
dashboard toggles and evaluator verdicts land on a live engine with no redeploy.
`dashboard/` is a React SPA reading Supabase directly (anon key, RLS-scoped).

## Docs map

| Doc | Read for |
|---|---|
| [`docs/research-log.md`](docs/research-log.md) | **what has been tested and what it returned.** Read before proposing any strategy - it records the dead ends and the rule against mining for variants |
| [`docs/strategy-lab.md`](docs/strategy-lab.md) | how a strategy is graded, the registries, gating, isolation, how to add one |
| [`docs/going-live.md`](docs/going-live.md) | **the real-money runbook** - the four guards, sizing, the exact procedure. Assumes no prior context |
| [`docs/safety-rails.md`](docs/safety-rails.md) | circuit breakers, TEST_MODE, RLS model, every bug found live and why |
| [`docs/architecture.md`](docs/architecture.md) | system layout, data flow, security model |
| [`docs/plugin-system.md`](docs/plugin-system.md) | the interface/plugin pattern, how to extend it |
| [`docs/engine.md`](docs/engine.md) | the engine in depth - loop mechanics, plugin behaviour |
| [`docs/dashboard.md`](docs/dashboard.md) | the React dashboard - structure, auth, how to add a view |
| [`infra/vps-setup.md`](infra/vps-setup.md) | VPS setup, and the optional second engine for live |
| [`APP-CREATION-PLANNING.md`](APP-CREATION-PLANNING.md) | the original phased roadmap and the reasoning behind early decisions |

## Conventions specific to this repo

- **Every plugin class takes exactly one constructor argument: `settings: Settings`.** Anything else arrives as a method parameter (`ExecutionEngine.execute(order, broker)`, `RiskEngine.validate_signal(..., broker, risk_pct)`) - broker facts are the broker's, not config's.
- **Secrets live in `.env` (root) and `dashboard/.env`** - both gitignored. `config/plugins.yaml` is not secret and is committed.
- **Migrations in `supabase/migrations/` are numbered and additive - never edit an applied one.** Applied by hand via the Supabase SQL editor (no Management API token is available locally, and no `supabase` CLI is in use).
- **RLS is the dashboard's real security boundary, not the anon key.** Grants are needed for *every* role that queries a table - a real 403 bug came from granting `anon` only. Everything requires sign-in since migration `0008`.
- **The engine runs via Task Scheduler on the VPS, never a Windows service/NSSM.** MT5's bridge needs an interactive desktop session; Session-0 can't provide one.
- **Logs are per-account** (`logs/engine-<ACCOUNT_KEY>.log`). Two engines sharing a `RotatingFileHandler` corrupt it.
- **Indicators (`engine/indicators.py`) are hand-rolled** - EMA/ATR/ADX, dependency-free on purpose.
- **`StrategyPlugin.evaluate()` returns `StrategyEvaluation(signal, reason)`** - every evaluation is logged with why, fired or not.
- **All Telegram copy lives in `engine/reporting.py`.** One grammar: icon + headline + the number that matters, then context, then at most one line of detail. The notifier only delivers.
- Windows-only project: PowerShell conventions, backslash paths fine, no Docker/Linux-only tooling for anything touching MT5.

## Rules that exist because breaking them costs real money

1. **Never generate strategy variants until one passes a backtest.** 60+ tests have produced *fewer* significant results than chance predicts. Mining harder manufactures a false positive - the one that gets funded and loses.
2. **Never lower the READY bar** to make something qualify.
3. **Never weaken a live guard** without the user explicitly asking, in that session. There are four, all off by default: `LIVE_TRADING_ENABLED`, `accounts.enabled`, `strategy_accounts.enabled`, `readiness == 'ready'`.
4. **`TEST_MODE` is not a safety guard.** It selects sizing style (`true` = demo micro-lot, `false` = real risk-based sizing). On a live account `TEST_MODE=true` is the *dangerous* setting.
5. **Screen with `scripts/backtest.py` before the lab.** Minutes vs months.
6. **Verify by exercising the real code path.** This repo has a history of green checks on broken things: `py_compile` passed on a *deleted* file; a backtest hardcoded to the wrong timeframes reported "no trades" instead of failing. Run the thing.

## Running things locally

```
# engine (from repo root, venv active)
pip install -e .
cp .env.example .env
python scripts/smoke_test_registry.py     # no external calls - proves the registry wires up
python scripts/run_engine.py              # the real loop (needs MT5 open + logged in)
python scripts/backtest.py <strategy_key> # screen a strategy against real history
python scripts/backtest.py <key> XAUUSD   # one symbol + its own half-split
python scripts/list_symbols.py            # broker symbol groups and their cost-in-R
python scripts/diagnose_costs.py          # every input to the cost model

# dashboard (from dashboard/)
npm install && cp .env.example .env && npm run dev
```

## On the VPS

```powershell
cd C:\ForexAI
git pull
Stop-ScheduledTask -TaskName "ForexAI-Engine"; Start-ScheduledTask -TaskName "ForexAI-Engine"
Get-Content C:\ForexAI\logs\engine-icmarkets-demo.log -Tail 25
```
