from __future__ import annotations

import urllib.request
import urllib.parse
import json

from engine.config import Settings
from engine.core.interfaces.notification import NotificationProvider
from engine.core.models import NotificationEvent


class TelegramNotifier(NotificationProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        self._url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        self._chat_id = settings.telegram_chat_id

    def notify(self, event: NotificationEvent) -> None:
        # The message carries its own icon + headline, so prefixing the raw
        # event_type just says the same thing twice in machine voice
        # ("[trade_closed] ✅ WIN ..."). Formatting lives in engine/reporting.py;
        # this plugin only delivers.
        payload = urllib.parse.urlencode(
            {"chat_id": self._chat_id, "text": event.message}
        ).encode()
        request = urllib.request.Request(self._url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read())
        if not result.get("ok"):
            raise RuntimeError(f"Telegram send failed: {result}")
