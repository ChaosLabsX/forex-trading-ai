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

    # --- Shadow AI review (engine/plugins/ai/, engine/review_scoring.py) ----
    # The review was previously gated on live_trading_enabled, which meant the
    # track record could not begin accumulating until the day real money was
    # already at stake - the one point at which you most want it to already
    # exist. This switch decouples the two: turn it on to start scoring Claude's
    # judgement against the demo lab's real fills, months before going live.
    #
    # Off by default because it costs an Opus call per reviewed signal and the
    # lab fires a lot of them. On a LIVE account reviews always run regardless of
    # this flag - every real-money signal is worth an opinion.
    ai_review_enabled: bool = False
    # Fraction of demo signals reviewed, so the cost of a track record is a dial
    # rather than a surprise. Sampling is random and therefore unbiased: the
    # scored subset stays representative of all signals, which is the only
    # property the comparison in review_scoring.py actually needs. Ignored on a
    # live account (100% there).
    ai_review_sample_pct: float = 10.0

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

    # Cap on simultaneously open positions PER STRATEGY (not per account).
    #
    # Per-strategy is what makes the lab valid: with a shared pool, strategies
    # race for slots and the loser's signal is silently never recorded, biasing
    # its track record by its neighbours' luck. Each strategy is an independent
    # experiment, so each gets its own budget.
    #
    # The default suits the DEMO LAB, where money is fake and the only cost of
    # breadth is broker load. infra/run-live-engine.ps1 pins live to 2, where
    # this is a real risk control rather than a data-collection knob - and live
    # runs one Ready strategy anyway, so per-strategy and per-account coincide.
    max_concurrent_trades: int = 4

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
