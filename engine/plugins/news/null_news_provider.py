from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.news import NewsProvider
from engine.core.models import NewsEvent


class NullNewsProvider(NewsProvider):
    """Always reports no upcoming events - i.e. no news blackout applied.

    Placeholder until a real economic-calendar API key is available (needs an
    account with a provider like TradingEconomics/Finnhub/FMP - that signup is
    a manual action, not something this plugin can do on its own). Swapping in
    a real provider later is a config change plus a new plugin class - no
    changes to the strategy or engine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_upcoming_events(
        self,
        window_minutes: int,
        currencies: tuple[str, ...] | None = None,
    ) -> list[NewsEvent]:
        return []
