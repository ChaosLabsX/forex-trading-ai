from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from engine.config import Settings
from engine.core.interfaces.news import NewsProvider
from engine.core.models import NewsEvent

logger = logging.getLogger("engine.news")

# Free weekly economic calendar (the ForexFactory calendar, via Faireconomy's
# mirror). No API key, no signup. Chosen over Finnhub because Finnhub's economic
# calendar is premium-only - this feed gives scheduled macro events with the
# currency and impact already in the shape the strategy needs. It is a
# community mirror with no SLA, so this provider fails OPEN (see below).
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# The mirror's CDN 403s the default urllib User-Agent; a browser UA gets through.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CACHE_TTL_SECONDS = 15 * 60  # the weekly feed doesn't change intra-quarter-hour
# Events that have just passed still matter: the strategy blacks out a window
# *around* an event (abs(time - now)), and the loop evaluates against the latest
# CLOSED bar, which lags now by up to an hour. Look back this far so a
# just-released print still suppresses entries.
LOOKBACK_MINUTES = 60

_IMPACT_MAP = {"high": "high", "medium": "medium", "low": "low", "holiday": "holiday"}


class ForexFactoryNewsProvider(NewsProvider):
    """Scheduled economic events from the free ForexFactory weekly feed.

    Fails open by design: any fetch/parse error logs a warning and falls back to
    the last good cache (or, if there is none yet, to no events = no blackout).
    A news blackout is a filter on top of the session filter and circuit
    breakers, not a safety-critical gate, so a transient feed outage must never
    crash or stall the engine - it just temporarily stops suppressing entries,
    which is the same behaviour as the old placeholder provider."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: list[NewsEvent] | None = None
        self._fetched_at: float = 0.0  # time.monotonic() of the last good fetch

    def get_upcoming_events(
        self,
        window_minutes: int,
        currencies: tuple[str, ...] | None = None,
    ) -> list[NewsEvent]:
        self._refresh_cache_if_stale()
        if not self._cache:
            return []

        now = datetime.now(timezone.utc)
        lower = now - timedelta(minutes=LOOKBACK_MINUTES)
        upper = now + timedelta(minutes=window_minutes)
        wanted = {c.upper() for c in currencies} if currencies else None

        events = []
        for event in self._cache:
            if not (lower <= event.time <= upper):
                continue
            if wanted is not None and event.currency.upper() not in wanted:
                continue
            events.append(event)
        return events

    def _refresh_cache_if_stale(self) -> None:
        if self._cache is not None and (time.monotonic() - self._fetched_at) < CACHE_TTL_SECONDS:
            return
        try:
            parsed = self._fetch_and_parse()
        except Exception:
            # keep serving the last good cache if we have one; only note it
            logger.warning("news feed refresh failed; serving %s cached events",
                           len(self._cache) if self._cache else "no")
            return
        self._cache = parsed
        self._fetched_at = time.monotonic()
        logger.info("news feed refreshed: %d events this week", len(parsed))

    def _fetch_and_parse(self) -> list[NewsEvent]:
        request = urllib.request.Request(
            FEED_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = json.loads(response.read())

        events: list[NewsEvent] = []
        for row in raw:
            try:
                # "country" in this feed is actually the currency code (USD, EUR...)
                currency = str(row["country"]).upper()
                impact = _IMPACT_MAP.get(str(row.get("impact", "")).lower(), "low")
                # dates are ISO-8601 with an offset, e.g. 2026-07-13T12:30:00-04:00
                when = datetime.fromisoformat(row["date"]).astimezone(timezone.utc)
            except (KeyError, ValueError, TypeError):
                continue  # skip any malformed row rather than fail the whole fetch
            events.append(
                NewsEvent(title=str(row.get("title", "")), time=when, currency=currency, impact=impact)
            )
        return events
