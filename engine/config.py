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
