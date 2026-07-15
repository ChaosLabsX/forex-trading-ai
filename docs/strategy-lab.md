# The strategy laboratory

How a trading idea earns the right to touch real money, and why it is built this
way. Read [`research-log.md`](research-log.md) first for what has already been
tried - it will stop you re-running a dead end.

## The shape of it

**Demo = laboratory. Live = production.** They run as two separate engine
processes against two separate MT5 terminals, sharing one codebase and one
database.

- The **demo lab** runs every enabled strategy, forever, including ones already
  Ready. It never stops - that is how a decayed strategy gets caught.
- The **live account** only ever runs a strategy the lab has certified, and only
  when you have personally switched it on. There is no fallback path: if nothing
  is Ready, live places nothing.

## Registries, not code

Four Supabase tables drive behaviour at runtime, so a toggle on the dashboard or
a verdict from the evaluator lands on a *running* engine with no redeploy:

| Table | Holds |
|---|---|
| `accounts` | every broker account (`icmarkets-demo`, `icmarkets-live`) |
| `strategies` | one row per plugin + its computed `readiness` verdict |
| `strategy_accounts` | per-account manual controls: `enabled`, `live_override`, `risk_pct` |
| `strategy_evaluations` | snapshot history per (strategy, account) - how decay becomes visible |

Adding a strategy is a plugin file + a line in `config/plugins.yaml`. The engine
**self-registers** it on startup (insert-missing-only - a blind upsert would
clobber readiness verdicts and your manual toggles), so it appears on the
dashboard by itself.

## How a verdict is reached (`engine/evaluator.py`)

Recomputed every `evaluation_interval_minutes` (30). **READY requires all of:**

- **≥ `readiness_min_trades_ready` (100)** closed trades with a recorded risk
- a bootstrap **95% CI on expectancy entirely above zero**
- profit factor ≥ `readiness_min_profit_factor` (1.2)
- max drawdown ≤ `readiness_max_drawdown_r` (15R)

Below that: `almost_ready` if expectancy is positive but unproven, else
`not_ready`.

Three properties that are not negotiable:

1. **Verdicts always derive from the DEMO lab.** Grading a strategy on the
   account it was already allowed onto would be circular.
2. **It is recomputed continuously**, so a decayed strategy is demoted
   automatically and loses live eligibility without anyone intervening.
3. **The CI is the test, not the point estimate.** A flattering average over 12
   trades is noise, and the interval is what says so.

Every change of verdict fires a Telegram alert with the statistics behind it.

## R-multiples, and why `risk_amount` exists

Everything is measured in **R** = the trade's initial risk. It is the only scale
on which EURUSD and XAUUSD are comparable.

`trades.risk_amount` and `trades.initial_stop_loss` are captured **at open**,
because trailing-stop management rewrites `trades.stop_loss` - so by the time a
trade closes, its original risk is gone. Realized R = `realized_pnl /
risk_amount`. Trades without `risk_amount` (anything pre-dating this) are
**excluded** from statistics rather than guessed at, as are any with
`void_reason` set.

## Strategy isolation (learned the hard way)

MT5 cannot tell you which strategy opened a position. Without ownership,
strategies see each other's trades - and two things went wrong, both fatal:

- **They blocked each other.** `has_open_position()` checked *any* position on a
  symbol, so whoever reached GBPUSD first silently suppressed everyone else's
  signal. **A signal that never fires is never recorded**, so every strategy's
  record was biased by its neighbours' luck.
- **They hedged.** Two strategies opened opposite sides of the same symbol on one
  bar, against a shared position snapshot that predated both trades.

`EngineLoop._refresh_ownership()` now maps ticket → strategy from our own
`trades` table each cycle, and each strategy sees **only its own positions**.
Each is an independent experiment sharing a price feed. That also makes
`max_concurrent_trades` a **per-strategy** budget rather than a pool they race
for. Positions we have no record of belong to nobody and stay hidden from
everyone.

## What may trade (`engine/gating.py`)

In order of authority:

1. an **account-wide block** beats everything (`live_trading_enabled` off,
   account disabled, registry unreadable);
2. a **live** account additionally requires `readiness == 'ready'`, unless
   `live_override` is deliberately set;
3. only then does the manual `enabled` toggle let it through.

If the registry cannot be read, everything is blocked - the engine refuses to
trade blind rather than falling back to a default.

## Adding a strategy

1. New file in `engine/plugins/strategies/`, implementing `StrategyPlugin`.
   Reuse `_common.py` for the instrument universe and news blackout.
2. Register it in `engine/registry.py` and list it in `config/plugins.yaml`.
3. **Screen it first**: `python scripts/backtest.py <key>` - two minutes against
   years of real history, net of costs. The lab takes weeks; the backtest takes
   minutes. Only promote survivors.
4. Restart the engine. It self-registers and appears on the dashboard.

### Testing a variation

Prefer **subclassing** over copying, so the logic is provably identical and only
the varied dimension moves - `donchian_trending_v1` (different instruments) and
`range_fade_h4_v1` (different timeframes) both do this, and their tests assert
`evaluate() is` the parent's function object. A copy silently drifts; a subclass
cannot.

## The standing rules

- **Do not generate strategy variants until one passes.** Across 60+ tests we
  found *fewer* significant results than chance produces. Mining harder finds a
  false positive, and that is the one that takes real money.
- **Do not lower the READY bar** to make something qualify. The bar is the
  product.
- **A new test needs a prior mechanism and a prediction about unseen data** -
  the standard `donchian_trending_v1` met, and failed honestly.
- **Screen with the backtest before the lab.** Waiting months to learn an idea is
  worthless is the slowest possible way to learn it.
