from __future__ import annotations

import logging

from engine.config import Settings
from engine.core.interfaces.notification import NotificationProvider
from engine.core.models import NotificationEvent

logger = logging.getLogger("engine.notify")


class ConsoleNotifier(NotificationProvider):
    """Logs via the `logging` module rather than print() - a bare print()
    goes nowhere under Task Scheduler (no attached console), while logging
    flows into whatever handlers scripts/run_engine.py configured (rotating
    file + console). No credentials needed - also exists to prove the
    plugin/registry pattern end-to-end without depending on Telegram/MT5/
    Supabase."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def notify(self, event: NotificationEvent) -> None:
        logger.info("[%s] %s", event.event_type, event.message)
