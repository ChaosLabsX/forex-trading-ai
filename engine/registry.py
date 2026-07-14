from __future__ import annotations

import importlib

from engine.config import PluginConfig, Settings

# kind -> key -> "module.path:ClassName". Every plugin class takes a single
# `settings: Settings` constructor argument. Entries here may name classes that
# don't exist yet - see PLAN.md for which phase implements which plugin.
PLUGIN_REGISTRY: dict[str, dict[str, str]] = {
    "broker": {
        "mt5": "engine.plugins.brokers.mt5_broker:MT5BrokerAdapter",
    },
    "market_data": {
        "mt5": "engine.plugins.market_data.mt5_market_data:MT5MarketDataProvider",
    },
    "strategy": {
        "ema_trend_v1": "engine.plugins.strategies.ema_trend_v1:EMATrendStrategy",
        "london_breakout_v1": "engine.plugins.strategies.london_breakout_v1:LondonBreakoutStrategy",
        "range_fade_v1": "engine.plugins.strategies.range_fade_v1:RangeFadeStrategy",
        "donchian_breakout_v1": "engine.plugins.strategies.donchian_breakout_v1:DonchianBreakoutStrategy",
    },
    "risk_engine": {
        "default": "engine.plugins.risk.default_risk_engine:DefaultRiskEngine",
    },
    "execution_engine": {
        "default": "engine.plugins.execution.default_execution_engine:DefaultExecutionEngine",
    },
    "news_provider": {
        # named "placeholder", not "null", to avoid clashing with YAML's null keyword
        "placeholder": "engine.plugins.news.null_news_provider:NullNewsProvider",
        "forexfactory": "engine.plugins.news.forexfactory_news_provider:ForexFactoryNewsProvider",
    },
    "notification": {
        "console": "engine.plugins.notifications.console_notifier:ConsoleNotifier",
        "telegram": "engine.plugins.notifications.telegram_notifier:TelegramNotifier",
    },
    "ai_provider": {
        "claude": "engine.plugins.ai.claude_ai_provider:ClaudeAIProvider",
    },
}


def load_plugin(kind: str, key: str, settings: Settings):
    try:
        path = PLUGIN_REGISTRY[kind][key]
    except KeyError as exc:
        raise ValueError(f"No plugin registered for {kind}={key!r}") from exc
    module_path, class_name = path.split(":")
    module = importlib.import_module(module_path)
    plugin_class = getattr(module, class_name)
    return plugin_class(settings)


class EngineComposition:
    """The wired-up set of subsystems the engine runs with. Built once at
    startup from config; nothing in the engine imports a concrete plugin
    module directly."""

    def __init__(self, plugin_config: PluginConfig, settings: Settings) -> None:
        self.broker = (
            load_plugin("broker", plugin_config.broker, settings) if plugin_config.broker else None
        )
        self.market_data = (
            load_plugin("market_data", plugin_config.market_data, settings)
            if plugin_config.market_data
            else None
        )
        self.strategies = [
            load_plugin("strategy", key, settings) for key in plugin_config.strategies
        ]
        self.risk_engine = (
            load_plugin("risk_engine", plugin_config.risk_engine, settings)
            if plugin_config.risk_engine
            else None
        )
        self.execution_engine = (
            load_plugin("execution_engine", plugin_config.execution_engine, settings)
            if plugin_config.execution_engine
            else None
        )
        self.news_provider = (
            load_plugin("news_provider", plugin_config.news_provider, settings)
            if plugin_config.news_provider
            else None
        )
        self.notifications = [
            load_plugin("notification", key, settings) for key in plugin_config.notifications
        ]
        self.ai_provider = (
            load_plugin("ai_provider", plugin_config.ai_provider, settings)
            if plugin_config.ai_provider
            else None
        )


def build_engine(
    settings: Settings | None = None,
    plugin_config: PluginConfig | None = None,
) -> EngineComposition:
    settings = settings or Settings()
    plugin_config = plugin_config or PluginConfig.from_yaml()
    return EngineComposition(plugin_config, settings)
