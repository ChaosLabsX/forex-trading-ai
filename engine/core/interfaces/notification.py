from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import NotificationEvent


class NotificationProvider(ABC):
    """Delivers a lifecycle/alert event somewhere (Telegram, email, etc.)."""

    @abstractmethod
    def notify(self, event: NotificationEvent) -> None: ...
