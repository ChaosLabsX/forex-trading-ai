from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import NewsEvent


class NewsProvider(ABC):
    """Upcoming scheduled events, for strategies/filters that need a news blackout."""

    @abstractmethod
    def get_upcoming_events(
        self,
        window_minutes: int,
        currencies: tuple[str, ...] | None = None,
    ) -> list[NewsEvent]: ...
