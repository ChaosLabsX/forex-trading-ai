from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.notification import NotificationProvider
from engine.core.models import NotificationEvent


class ConsoleNotifier(NotificationProvider):
    """Prints to stdout. No credentials needed - exists to prove the plugin/
    registry pattern end-to-end without depending on Telegram/MT5/Supabase."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def notify(self, event: NotificationEvent) -> None:
        print(f"[{event.event_type}] {event.message}")
