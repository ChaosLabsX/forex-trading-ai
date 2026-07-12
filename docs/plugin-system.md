# Plugin system

The engine is strategy-agnostic and, more generally, implementation-agnostic for
every major subsystem. Core code only ever depends on the abstract interfaces in
`engine/core/interfaces/`; it never imports a concrete plugin module directly.

## Interfaces

| Interface | File | Contract |
|---|---|---|
| `BrokerAdapter` | `broker.py` | connect/auth, account state, place/modify/close orders |
| `MarketDataProvider` | `market_data.py` | ticks/candles for a symbol+timeframe |
| `StrategyPlugin` | `strategy.py` | `evaluate(context) -> Signal \| None` |
| `RiskEngine` | `risk.py` | `validate_signal(...) -> RiskDecision` |
| `ExecutionEngine` | `execution.py` | turn an approved order into broker actions; manage open positions |
| `NewsProvider` | `news.py` | upcoming high-impact events for a news-blackout filter |
| `NotificationProvider` | `notification.py` | deliver a lifecycle/alert event |
| `AIProvider` | `ai_provider.py` | optional pre-execution review of a signal |

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

See [`PLAN.md`](../APP-CREATION-PLANNING.md) for which plugin is implemented in
which phase. As of Phase 0, only `ConsoleNotifier` is a real implementation - it
exists solely to prove this wiring end-to-end (`scripts/smoke_test_registry.py`)
without requiring any external account.
