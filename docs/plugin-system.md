# Plugin system

The engine is strategy-agnostic and, more generally, implementation-agnostic for
every major subsystem. Core code only ever depends on the abstract interfaces in
`engine/core/interfaces/`; it never imports a concrete plugin module directly.

## Interfaces

| Interface | File | Contract | Active plugin |
|---|---|---|---|
| `BrokerAdapter` | `broker.py` | connect/auth, account state, place/modify/close orders, `get_closed_position_pnl(id)` | `mt5` |
| `MarketDataProvider` | `market_data.py` | ticks/candles for a symbol+timeframe | `mt5` |
| `StrategyPlugin` | `strategy.py` | `evaluate(context) -> StrategyEvaluation(signal, reason)` | `ema_trend_v1` |
| `RiskEngine` | `risk.py` | `validate_signal(...) -> RiskDecision` | `default` |
| `ExecutionEngine` | `execution.py` | `execute(order, broker) -> Position`; `manage_open_position(position, tick, broker)` | `default` |
| `NewsProvider` | `news.py` | upcoming high-impact events for a news-blackout filter | `placeholder` (always empty - real calendar needs an API key) |
| `NotificationProvider` | `notification.py` | deliver a lifecycle/alert event | `console` + `telegram` |
| `AIProvider` | `ai_provider.py` | `review_signal(signal, context) -> AIVerdict`, shadow mode only | `claude` |

`ExecutionEngine` and `BrokerAdapter` take the broker/relevant collaborator as
an explicit method argument rather than holding a reference - every plugin
constructor still takes just `settings: Settings`, so dependencies between
subsystems are passed at the call site (in `engine/loop.py`), not wired at
construction time.

## How wiring works

1. `config/plugins.yaml` names which plugin key backs each subsystem (e.g.
   `broker: mt5`, `strategies: [ema_trend_v1]`). Not a secret - it's committed.
2. `engine/registry.py` maps `(kind, key)` to an import path
   (`"module:ClassName"`) in `PLUGIN_REGISTRY`.
3. `build_engine()` reads both, dynamically imports and instantiates the
   configured classes, and returns an `EngineComposition` with everything
   wired. Every plugin constructor takes a single `Settings` argument (secrets
   from `.env`).
4. Slots left `null`/empty in `plugins.yaml` are simply unwired - the engine
   runs with whatever subset is configured. This is how Phase 0 can boot with
   only a `NotificationProvider` (`console`) long before MT5/Supabase/Telegram
   exist.

## Adding a new plugin

1. Implement the relevant interface as a new class in `engine/plugins/<subsystem>/`.
2. Register it: add an entry to `PLUGIN_REGISTRY[kind][key]` in `registry.py`.
3. Point `config/plugins.yaml` at the new key.

No changes anywhere else - not in the engine loop, not in other plugins, not in
the dashboard or database schema. This is what "swap a strategy/broker/AI
provider without touching core" means in practice.

## Why hand-rolled ABCs + a config registry, not `pluggy`/entry-points discovery

Frameworks for dynamic plugin discovery earn their keep when independent third
parties ship plugins you didn't write, against hook specs you publish. Every
plugin here is code written for this project - a plain abstract base class per
subsystem plus the small registry above gets the same "swap without touching
core" property with one less dependency. Revisit only if the plugin roster grows
into something like a marketplace of externally authored strategies.

## Reference implementation status

All 8 interfaces have at least one real, live-verified implementation (see the
table above and `config/plugins.yaml`) - `scripts/smoke_test_registry.py`
confirms zero unimplemented slots. `ema_trend_v1` (EMA/ADX trend-following) and
`claude` (shadow-mode review) are explicitly *reference* implementations - the
whole point of this architecture is that they're swappable for a different
strategy or AI provider without touching the engine, risk logic, execution
logic, dashboard, or database. See [`docs/engine.md`](engine.md) for what each
active plugin actually does, and [`APP-CREATION-PLANNING.md`](../APP-CREATION-PLANNING.md)
for which phase built which plugin and why.
