# MT5 + IC Markets Automated Trading App — Build Plan

Independent project. No shared code, credentials, repo, Supabase project, or Telegram
bot with the OKX app. That project is read-only reference material.

## Hard constraint

MT5 has no public REST API. The official `MetaTrader5` Python package requires a
locally running, logged-in MT5 terminal and is Windows-only. It's a synchronous IPC
bridge with no push/callback model — "tick-driven" means a tight sub-second polling
loop, not true event push. Execution logic runs as a persistent process on a Windows
VPS with MT5 open and logged into IC Markets 24/7. There is no serverless option for
the execution side.

## Locked-in decisions

- **Instruments (v1):** EUR/USD, GBP/USD, USD/JPY, XAU/USD (Gold).
- **Sizing (v1):** fixed micro lot (e.g. 0.01), mirrors OKX app's `TEST_MODE` pattern.
- **AI decision layer:** added later (Phase 5), not from day one.
- **Dashboard hosting:** GitHub Pages (static SPA) + Supabase, not Vercel/Netlify.
- **Repo/Supabase provisioning:** user creates both, hands Claude the URL/keys.
- **Platform is strategy-agnostic by design** (added after initial review): the
  engine has no knowledge of any specific strategy's rules. Strategies are plugins
  implementing a common interface, swappable without touching core code.
- **Development environment: local Windows PC first.** All phases through the AI
  layer (Phase 5) are built and verified running locally, with the MT5 terminal
  installed and logged into the demo account on the same machine. VPS provisioning
  and deployment is deferred to Phase 6, not required to build or test anything
  before that.
- **MT5 credentials stay out of `.env` where possible:** `mt5.initialize()` attaches
  to an already-running, already-logged-in terminal without needing login/password
  passed in code. `.env` only needs `MT5_LOGIN`/`MT5_PASSWORD` filled in for
  unattended/headless startup (relevant once running as a service in Phase 6) —
  keeping the demo password out of a file entirely for as long as possible is the
  safer default.

## Plugin architecture

Every major subsystem is an abstract interface in `engine/core/interfaces/`;
concrete implementations live under `engine/plugins/<subsystem>/` and are wired
together at startup by a config-driven registry (`engine/registry.py`) — never by
direct imports between subsystems. Swapping an implementation means writing a new
class against the existing interface and flipping a config value; it never requires
touching the execution engine, risk engine, broker code, dashboard, or database.

Interfaces, one per subsystem:

| Interface | Contract | First implementation |
|---|---|---|
| `BrokerAdapter` | connect/auth, account state, place/modify/close orders | MT5 (Phase 1) |
| `MarketDataProvider` | ticks/candles for a symbol+timeframe | MT5 (Phase 1) |
| `StrategyPlugin` | evaluate market context → `Signal \| None` | EMA trend-following v1 (Phase 2) |
| `RiskEngine` | validate a signal against account/risk state → approve/reject/size | default rules engine (Phase 3) |
| `ExecutionEngine` | turn an approved signal into broker orders, track lifecycle | MT5-backed (Phase 3) |
| `NewsProvider` | upcoming high-impact events for the news-blackout filter | TBD calendar source (Phase 2) |
| `NotificationProvider` | deliver lifecycle/alert events | Telegram (Phase 1) |
| `AIProvider` | optional signal review before execution | Claude (Phase 5) |

**Why hand-rolled ABCs + a config-driven registry, not a plugin framework
(`pluggy`, setuptools entry-points discovery):** frameworks like `pluggy` earn their
keep when independent third parties author plugins against your hook specs. Every
plugin here is code I write myself — a plain abstract base class per subsystem plus
a small registry that instantiates whatever class is named in config gets the same
swap-without-touching-core benefit with one less dependency to maintain. This is a
reversible, low-risk internal choice, worth revisiting only if the plugin roster
grows enough (e.g. a marketplace of third-party strategies) that dynamic discovery
starts paying for itself.

Plugin selection lives in config (`config.yaml` / env vars) for now; once the
dashboard exists (Phase 4) this can move to the Settings UI, matching the
"keys/config via UI, not hardcoded" pattern already agreed for API keys.

The EMA trend-following strategy (below) is the **first reference `StrategyPlugin`
implementation**, used to build and test the rest of the platform end-to-end — not
a strategy the engine is designed around. SMC/ICT-style, indicator-based,
AI-assisted, and ML-based strategies are all meant to slot in later as additional
`StrategyPlugin` implementations with zero core changes.

## Architecture, at a glance

| Decision | Choice | Why (rejected alternative) |
|---|---|---|
| MT5 access | Self-hosted terminal on the VPS | vs. MetaApi.cloud — self-hosting avoids recurring fees, an extra network hop, and a third party sitting in the trade-execution path. Trade-off: you own uptime/crash recovery — offset by a supervised service + alerting. |
| Engine structure | Single Python modular monolith, subsystems wired via the plugin interfaces above | vs. microservices — MT5 access is local-only anyway, so network-split services would add latency and ops surface for no benefit at one-VPS scale. |
| Dashboard ↔ VPS commands | Postgres `commands` table, VPS subscribes via **Supabase Realtime** | vs. polling (too slow for an emergency stop) or a dedicated broker like Redis/RabbitMQ (unneeded infra for a single-user queue). |
| Dashboard security model | Static SPA + Supabase anon key; **RLS policies are the actual boundary** (narrow `SELECT`s, writes only via validated Postgres RPCs) | Necessary because GitHub Pages can't hide secrets — the service-role key stays VPS-side only. |
| Process supervision | NSSM-wrapped Windows service (auto-start, auto-restart on crash) — **applied at VPS deployment (Phase 6)**, not during local development | vs. hand-rolled `pywin32` service (more code, no benefit) or Task Scheduler (weaker restart-on-crash semantics). Locally, the engine just runs as a plain script while developing. |
| Repo layout | Single monorepo: `/engine`, `/dashboard`, `/docs`, `/infra` | vs. split repos — unnecessary sync overhead for a solo project. |

## Reference strategy plugin v1 — multi-timeframe trend-following

Trend-following is the style with the most robust long-run track record in liquid
FX/commodities (decades of CTA/managed-futures precedent), has a favorable
cut-losses/let-winners-run payoff shape, and produces bounded, explainable signals
that a future AI review layer (Phase 5) can reason over cleanly. It exists purely as
the first `StrategyPlugin` implementation — the engine has no special-case logic
for it.

- **Regime filter (H4/Daily):** EMA(50) vs EMA(200) defines allowed trade direction;
  ADX(14) > 20 gates out flat/choppy conditions (the main failure mode for
  trend-following systems).
- **Entry trigger (H1):** EMA(20)/EMA(50) crossover in the direction the regime
  filter allows. (v2 iteration: replace with pullback-to-EMA entries for better
  stop placement — deferred to keep v1 simple and shippable.)
- **Stop-loss / target:** ATR(14)-based (e.g. 1.5×ATR stop, 2–2.5×ATR target) so
  risk adapts per-instrument automatically instead of using fixed pip values.
  Move stop to breakeven at 1×ATR profit, then trail the remainder.
- **Filters:** London/NY session overlap only; high-impact news blackout window
  around scheduled events (calendar data source TBD — Phase 2 detail).
- **Safety rails (default `RiskEngine` plugin):** max concurrent open trades;
  circuit breaker after N consecutive stop-losses/day; independent max-daily-loss %
  cap; all controlled by the `TEST_MODE` flag.

Sizing stays fixed-lot through the early phases; revisit % equity risk sizing once
the system has a demo track record.

## Phased roadmap

Each phase ends with a concrete, checkable exit condition before starting the next.

**Phase 0 — Foundations** ✅ complete
Scaffolded the monorepo (`/engine`, `/dashboard`, `/docs`, `/infra`); defined the 8
core plugin interfaces and shared data models; built the config-driven plugin
registry/composition root (verified working end-to-end via
`scripts/smoke_test_registry.py`); `TEST_MODE` flag and secrets-handling pattern
(gitignored `.env`); baseline docs. GitHub repo, Supabase project ("Forex Trading
AI"), and Telegram bot created and wired into `.env`; Supabase connectivity
verified live; Telegram bot token verified valid (pending: message the bot once so
Telegram associates the chat - bots can't push to a chat that hasn't messaged them
first). IC Markets demo account server noted (`ICMarketsSC-Demo`).

**Phase 1 — MT5 broker adapter + engine skeleton + data feed** ← current
Implement the first real plugins: `MT5BrokerAdapter` and an MT5 `MarketDataProvider`
(against a locally-running, logged-in MT5 terminal), plus the polling/candle-
aggregation loop (H1 execution + H4/Daily context) and a Telegram
`NotificationProvider` for crash/disconnect alerting. Runs as a plain local script -
no service wrapping yet (that's Phase 6).
*Exit: engine runs unattended locally for 24h+ through the plugin-selected MT5
broker, survives a manual restart, and alerts via Telegram on disconnect.*

**Phase 2 — Reference strategy plugin (rules only, no execution)**
Implement the EMA trend-following v1 `StrategyPlugin` (regime filter, entry
trigger, ATR stop/target calc) and a first `NewsProvider` implementation for the
blackout filter. Log every candidate signal — fired or filtered, with why — to
Supabase. Backtest against historical data before moving on.
*Exit: engine correctly logs signals against live demo data for several days via
the plugin-selected strategy; backtest results are sane.*

**Phase 3 — Risk engine + execution engine (demo)**
Implement the default `RiskEngine` plugin (`TEST_MODE`-driven sizing, circuit
breakers) and `ExecutionEngine` plugin (order placement/modify/close through the
`BrokerAdapter` interface), the phased trade-lifecycle state machine in Supabase,
and the Realtime-driven `commands` table for dashboard control.
*Exit: engine autonomously runs a full trade lifecycle correctly over a sustained
demo test period (1–2 weeks), with working circuit breakers.*

**Phase 4 — Dashboard**
React + TypeScript SPA (signals, open trades, history/performance, engine health,
manual pause/resume/emergency-close), Settings UI for keys/config — including
which plugin is active per subsystem — deployed to GitHub Pages via GitHub Actions.
*Exit: full monitoring and control from the browser, no direct VPS access needed.*

**Phase 5 — AI decision layer**
Implement the first `AIProvider` plugin (Claude) as an optional pre-execution
reviewer: rules-based signal fires → Claude gets technical + risk context →
confidence/go-no-go + rationale, logged alongside the signal. Shadow mode first
(logs only), promoted to gating once validated.
*Exit: documented comparison of rules-only vs. AI-reviewed outcomes.*

**Phase 6 — VPS deployment + live-readiness checklist**
Provision the Windows VPS ([`infra/vps-setup.md`](infra/vps-setup.md)), move the
already-locally-verified engine over, wrap it as an NSSM Windows service
(auto-start, auto-restart on crash). Define objective demo criteria to graduate
(minimum trade sample size, drawdown behavior, uptime track record). Security pass
(secrets rotation, RLS audit, VPS hardening/firewall/restricted remote access).
Confirm the plugin boundaries held in practice — swapping any one plugin during
development never required touching another subsystem. Document the live cutover
procedure (`TEST_MODE` off, live sizing rules, rollback plan).
*Exit: a deliberate, documented go/no-go decision — never automatic.*

## Docs

One doc per subsystem plus an architecture overview, added as each phase lands
(`/docs/architecture.md`, `/docs/plugin-system.md`, `/docs/engine.md`,
`/docs/dashboard.md`, `/docs/strategy-ema-trend-v1.md`, `/docs/safety-rails.md`).

---
*Status: Phase 0 complete. Phase 1 starting — needs the MT5 terminal installed and
logged into the IC Markets demo account locally, and one message sent to the
Telegram bot to activate it.*
