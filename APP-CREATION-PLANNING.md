# MT5 + IC Markets Automated Trading App — Build Plan

Independent project. No shared code, credentials, repo, Supabase project, or Telegram
bot with the OKX app. That project is read-only reference material.

> **New to this repo? Read [`CLAUDE.md`](CLAUDE.md) first** — it's the short
> orientation doc (what's built, how it fits together, conventions, how to run
> it) with links to everything below. This file is the detailed phase-by-phase
> log and roadmap; the **Status** line at the very bottom is the current
> single source of truth for what's done vs. pending.

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

**Phase 1 — MT5 broker adapter + engine skeleton + data feed** ✅ core loop built and verified
`MT5BrokerAdapter` and `MT5MarketDataProvider` implemented and verified live
against the real demo account (account state, ticks, H1/H4/D1 candles).
`TelegramNotifier` implemented and verified live. `engine/loop.py` +
`scripts/run_engine.py`: connect/reconnect with backoff, Telegram alerts on
connect/disconnect transitions, heartbeat and candle persistence to Supabase on
a 60s interval. Schema applied (`supabase/migrations/0001_phase1_market_data.sql`:
`candles`, `engine_heartbeats`, both RLS-enabled with no policies yet - deny-all
by default until Phase 4 defines dashboard-facing policies).
Verified with a live 90s run: connected, sent 2 heartbeats 60s apart, persisted
300 H1 + 250 H4 + 90 D1 candles for all 4 instruments, confirmed via direct
Supabase query. (H4 window later corrected from an initial 150 to 250 - see
Phase 2 notes; 150 was too small for the strategy's own EMA(200) requirement.)
*Remaining for full exit: leave it running unattended for 24h+ and confirm it
survives a manual restart without issue - runs as a plain foreground script for
now (Ctrl+C to stop); no service wrapping until Phase 6.*

**Phase 2 — Reference strategy plugin (rules only, no execution)** ✅ built, backtested, verified live
`EMATrendStrategy` implemented (H4 EMA50/200 regime + ADX(14) gate, H1 EMA20/50
crossover entry, ATR(14) stop/target, London/NY session filter, news blackout
check) plus `NullNewsProvider` (always-empty placeholder - a real economic
calendar needs an API key from a provider of your choice, e.g. TradingEconomics/
Finnhub/FMP; that account signup is a manual action, deferred rather than
blocking Phase 2). `signals` table added
(`supabase/migrations/0002_phase2_signals.sql`) and wired into the loop, which
now evaluates every configured strategy against fresh candles each refresh cycle
and logs every evaluation - fired or filtered, with why - deduplicated per
closed bar.

Two real bugs found and fixed during this phase, not just written and assumed
correct: (1) `StrategyPlugin.evaluate()` originally returned bare `Signal | None`,
which can't carry a filter reason - extended to return a `StrategyEvaluation
(signal, reason)` wrapper, since PLAN.md's own requirement to log *why* a signal
was filtered couldn't be satisfied by the original interface. (2) the engine was
passing MT5's still-forming current bar straight into indicator calculations,
which would make a crossover reading flip-flop as price moved within the hour -
fixed by trimming to closed-only bars before every strategy evaluation.

Backtested against ~4000 H1 bars (~5.5 months) of real historical data per
instrument, replaying the exact same logic and window sizes the live loop uses:
16 signals total across 4 instruments, R-multiples landing exactly on the
designed 1.5/2.0 ATR ratio (-1.00R losses, +1.33R wins) - confirms the logic is
internally consistent, though the sample is far too small for the win rates
themselves to mean anything yet. Live-verified: ran the full loop against the
real demo account, confirmed exactly one signal-evaluation row per instrument
landed in Supabase, and confirmed re-running within the same closed bar does
not produce duplicate rows.
*Exit met for the core loop; only a live multi-day observation period (naturally
overlapping the Phase 1 24h+ soak test) remains before calling Phase 2 fully done.*

**Phase 3 — Risk engine + execution engine (demo)** — built and fully verified live
`DefaultRiskEngine` (`TEST_MODE` fixed-lot sizing, max-concurrent-trades cap,
consecutive-losing-trades circuit breaker, max-daily-loss % circuit breaker -
both breakers driven off real numbers computed from MT5's own closed-deal
history, not placeholders) and `DefaultExecutionEngine` (order placement through
`BrokerAdapter`) implemented. Trade lifecycle (`trades` table, migration
`0003_phase3_trades.sql`) wired into `engine/loop.py`: an approved signal opens
a real order and a Supabase row, and every cycle reconciles Supabase's "OPEN"
rows against MT5's actual open positions to detect closures, fetch the real
realized P&L via MT5's deal history, and fire a Telegram alert - both on open
and on close.

`ExecutionEngine`'s interface picked up a `broker` parameter on `execute()`/
`manage_open_position()` (plugins otherwise only take `Settings`, so the broker
has to be passed in rather than held) - a necessary completion of the Phase 0
interface, not a new direction. Same reasoning for `BrokerAdapter` gaining
`get_closed_position_pnl()`, needed to look up what a closed trade actually
made/lost.

The dashboard's `commands` table (originally scoped to this phase) is deferred
to Phase 4 - it only does anything once a dashboard exists to write to it.

Live verification complete once the market reopened Monday. Along the way this
surfaced (and fixed) two real bugs, not just confirmed the happy path:

1. **MT5 timestamps are broker server time, not UTC** (measured live: ~3h
   offset on this IC Markets account). Was silently skewing the session-time
   filter and the daily circuit-breaker boundary. Fixed with a runtime-measured
   (not hardcoded) offset - see `docs/safety-rails.md`.
2. **A client-side order error doesn't mean the order failed.** An attempt
   that raised `MT5ConnectionError` (MT5 retcode 10012, TIMEOUT) had actually
   filled on the broker's side - the original code would have lost track of it
   entirely (a real position with no `trades` row, invisible to reconciliation
   forever). `_open_trade()` now detects and recovers this case instead of
   silently orphaning the position - see `docs/safety-rails.md`.

With both fixed, drove a real signal through the full pipeline end-to-end
against the live demo account: `DefaultRiskEngine` approved it, the order
filled, `_reconcile_closed_trades()` (the real production code path, not a
shortcut) detected the close, fetched the real P&L via MT5's deal history
(+0.10), updated the `trades` row, and fired the Telegram alert. Two earlier
attempts had failed first with retcode 10027 (AutoTrading disabled - user
enabled it) and 10018 (market closed - it was the weekend), both MT5 correctly
refusing the order rather than a bug.
*Exit: met. Remaining: a sustained multi-day demo run to prove circuit
breakers and the lifecycle hold up over time (same ongoing soak test as
Phase 1).*

**Phase 4 — Dashboard** — built and verified live (except real-credential login)
React + TypeScript SPA (Vite) with public read-only monitoring (engine health/
heartbeat, open trades, trade history + win-rate/P&L stats, recent signals)
using the Supabase anon key - RLS policies (migration
`0005_phase4_dashboard_rls.sql`) are the real access boundary. Manual controls
(pause/resume/emergency-close-all) require Supabase Auth sign-in and write to
the `commands` table via RLS restricted to `authenticated`, checked against
`auth.uid()`.

**Architecture change made while building this (not a new direction, a
correction):** the original plan called for the engine to consume `commands`
via a Supabase Realtime (websocket) subscription. Since `engine/loop.py`
already polls every 2 seconds for connection health, checking `commands` on
that same tick gets pause/emergency-stop reacting within ~2 seconds - plenty
fast for this system - without a websocket client dependency. Switched to
polling; verified live (see below).

Public sign-ups are disabled on the Supabase Auth project - only one invited
user exists. The user was invited by email (Supabase's invite flow), never a
password Claude set or saw.

**Deferred, not built:** a Settings UI for editing plugin selection/API keys
from the browser. Doing this safely would need real user-management (not just
a single shared login) and a secure way to edit `.env`-equivalent secrets from
a static site talking only to the anon key - a meaningfully bigger scope than
"add a form." Config changes still go through `config/plugins.yaml` + `.env`
directly for now.

Live-verified: dashboard correctly renders real Supabase data (heartbeat,
empty trades tables, real signal history) with no auth; sign-in correctly
round-trips to Supabase Auth and displays real errors (tested with a
deliberately wrong password - correct login is pending the user setting their
password via the invite email, since Claude never handles that password
directly). Pause/resume commands verified end-to-end earlier in Phase 3/4
crossover work (inserted manually, consumed by the engine within one tick,
marked processed, Telegram-notified).
*Exit: full monitoring works now; full control-loop verification needs the
user to complete sign-in themselves once, then confirm the buttons work.*

**Phase 5 — AI decision layer** — built and verified live
`ClaudeAIProvider` implemented (`claude-sonnet-5`, structured tool-use output
for a reliable `approved`/`confidence`/`rationale` verdict). Runs in shadow
mode: every fired signal gets reviewed after the risk engine's own decision,
logged to a new `ai_reviews` table (migration `0006_phase5_ai_reviews.sql`,
foreign-keyed to `signals`) - the verdict never gates execution yet, exactly
as planned. Dashboard's signal feed now joins and displays the AI verdict
alongside each signal.

Verified live with two hand-built test cases before wiring into the loop: a
clean trend-following setup with good R:R and a clean account (approved,
72% confidence, cited the specific EMA/ADX/R:R reasoning) and a deliberately
bad one - poor R:R, weak ADX, account already under daily-loss pressure
(correctly rejected, 90% confidence, cited the specific numbers). A third
test using a placeholder "verification test signal" reason string was also
correctly rejected, with Claude explicitly noting there was no real market
rationale to evaluate - a good sign it's reading the actual content rather
than pattern-matching on the numeric fields alone. Full pipeline (signal
insert → id capture → AI review → linked row → dashboard join) verified
end-to-end against the real Supabase project and a real API call.

`SupabaseClient.insert()` gained an optional `returning` flag (via PostgREST's
`Prefer: return=representation`), needed so a logged signal's id could be
captured and passed to its linked AI review - a small, necessary completion,
not a new direction.
*Exit: shadow-mode comparison data is now being generated on every fired
signal. A documented rules-only vs. AI-reviewed comparison needs a real
sample of live signals to accumulate first - revisit once Phase 3's live
trading has run for a while.*

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
*Status (2026-07-12): Phases 0-2 built and verified live end-to-end. Phase 3
built, risk engine approval path verified live; final execution/close/
reconciliation verification is blocked on the weekend forex market being
closed (confirmed via a correctly-rejected order, not a bug) and will resume
once markets reopen. Phase 4 dashboard fully working end-to-end - user set
their password, signed in, and confirmed the control buttons work (a couple
of real bugs surfaced and fixed along the way: `authenticated`-role 403s from
a grants oversight, a stray `/forex-trading-ai/` prefix in the local dev URL,
a missing Supabase Auth `site_url` config, and a missing "set password" step
in the UI - see migrations 0005-0007 and git history). Phase 5 (AI shadow-mode
review) built and verified live, generating comparison data on every fired
signal going forward.

`scripts/run_engine.py` ran continuously as a detached background process from
2026-07-12 22:02 to 2026-07-13 ~02:35 local time (~4.5h, healthy the whole
time - no crashes, reconnects, or missed heartbeats) before being intentionally
stopped so the user could shut down the laptop overnight (zero open positions
at the time, no risk). Not a crash - a deliberate pause. **Resume by running
`python scripts/run_engine.py` again** (or asking Claude to) once the laptop's
back up; the 24h+ soak clock restarts from zero at that point. This will keep
happening on this hardware until Phase 6 moves the engine to a VPS that
doesn't depend on this laptop staying on.

**Phase 3's live verification completed 2026-07-13 once the market reopened**
(see Phase 3 section above) - full fill → close → reconciliation → real P&L →
Telegram confirmed against the live demo account, with two real bugs found and
fixed in the process (MT5 server-time-vs-UTC timestamps, and order-timeout
orphaned-position recovery - both in `docs/safety-rails.md`). Phases 0-5 are
now all built and live-verified.

Only Phase 6 (VPS deployment + live-readiness checklist) remains, intentionally
not started - VPS provisioning is a purchase decision for the user to make and
initiate. The user is currently comparing VPS providers (leaning toward
InterServer's 4-slice plan, ~$12/month, for initial testing) before committing.*
