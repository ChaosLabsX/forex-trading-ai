from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and environment-specific values. Loaded from .env, never committed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_mode: bool = True

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    mt5_login: str | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_terminal_path: str | None = None

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    anthropic_api_key: str | None = None

    # Which account row (public.accounts.key) this engine process IS. One engine
    # process serves exactly one account; the live engine runs with its own .env
    # setting ACCOUNT_KEY=icmarkets-live. Everything this process writes is
    # tagged with it, and its demo/live behaviour is read from that row.
    account_key: str = "icmarkets-demo"

    # --- The live master switch -------------------------------------------
    # THE guard for real-money execution. Off by default, and deliberately NOT
    # derived from "sizing isn't built yet" - a safety property that depends on
    # a feature being missing evaporates the moment the feature lands. This is
    # an explicit switch that stays off until you decide otherwise, and
    # engine/gating.py blocks every strategy on a live account while it is off.
    live_trading_enabled: bool = False

    # --- Live position sizing (engine/sizing.py) ---------------------------
    # Fallback risk per trade when a strategy/account pair has no risk_pct of
    # its own (strategy_accounts.risk_pct). max_risk_pct is a hard ceiling that
    # a per-strategy value can never exceed - a fat-fingered 50 stays 2.
    default_risk_pct: float = 0.5
    max_risk_pct: float = 2.0
    # Refuse a trade whose margin would eat more than this share of free margin.
    max_margin_use_pct: float = 25.0

    # --- Readiness thresholds (engine/evaluator.py) -------------------------
    # A strategy is only READY when a bootstrap 95% CI on its expectancy sits
    # entirely above zero on a large-enough sample. These are deliberately
    # strict: the cost of a false "ready" is real money.
    readiness_min_trades_ready: int = 100
    readiness_min_trades_almost: int = 30
    readiness_min_profit_factor: float = 1.2
    readiness_max_drawdown_r: float = 15.0  # demote if the demo curve bleeds worse than this
    evaluation_interval_minutes: int = 30

    # --- Daily Telegram summary --------------------------------------------
    # HH:MM in UTC. Only ONE engine process should have this enabled, or you get
    # duplicate summaries - the live engine's .env should set it to false.
    daily_summary_enabled: bool = True
    daily_summary_utc_time: str = "21:00"

    # Trailing-stop management (DefaultExecutionEngine.manage_open_position).
    # Thresholds are in R = the trade's initial risk (|entry - first stop|), so
    # they scale automatically per instrument/ATR instead of a fixed pip value.
    trail_enabled: bool = True
    breakeven_at_r: float = 1.0  # move stop to entry once +this many R in profit
    trail_start_r: float = 2.0  # start trailing once beyond this many R
    trail_distance_r: float = 1.0  # keep the stop this many R behind price while trailing


class PluginConfig(BaseSettings):
    """Which concrete plugin implements each subsystem. Not a secret - safe to
    commit. Will move to the dashboard Settings UI once it exists (Phase 4)."""

    broker: str | None = None
    market_data: str | None = None
    strategies: list[str] = []
    risk_engine: str | None = None
    execution_engine: str | None = None
    news_provider: str | None = None
    notifications: list[str] = []
    ai_provider: str | None = None

    @classmethod
    def from_yaml(cls, path: str | Path = "config/plugins.yaml") -> "PluginConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(**data)
