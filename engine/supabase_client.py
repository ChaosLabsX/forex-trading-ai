from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from engine.config import Settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5

# Worth trying again: the gateway or the database was busy, not wrong. A 4xx is
# excluded on purpose - a malformed request does not improve on the second ask.
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class SupabaseError(RuntimeError):
    pass


class SupabaseClient:
    """Minimal PostgREST wrapper - no supabase-py dependency needed for the
    handful of insert/upsert/select/update calls the engine makes."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        self._base = settings.supabase_url.rstrip("/") + "/rest/v1"
        self._key = settings.supabase_service_role_key

    def insert(self, table: str, rows: list[dict], returning: bool = False) -> list[dict] | None:
        extra_headers = {"Prefer": "return=representation"} if returning else None
        return self._request("POST", f"/{table}", rows, extra_headers=extra_headers)

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        query = urllib.parse.urlencode({"on_conflict": on_conflict})
        self._request(
            "POST",
            f"/{table}?{query}",
            rows,
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )

    def select(self, table: str, filters: dict[str, str]) -> list[dict]:
        """`filters` uses PostgREST syntax, e.g. {"status": "eq.OPEN"}."""
        query = urllib.parse.urlencode(filters)
        return self._request("GET", f"/{table}?{query}", None) or []

    def count(self, table: str, filters: dict[str, str]) -> int:
        """Exact row count, without transferring the rows.

        Not len(select(...)): PostgREST caps a select at its configured maximum
        (1000 by default), so counting rows client-side silently under-reports
        the moment a table outgrows one page - and reports a suspiciously round
        number while doing it. The server counts instead; Range keeps the body
        to a single row.
        """
        query = urllib.parse.urlencode(filters)
        request = urllib.request.Request(
            f"{self._base}/{table}?{query}",
            method="GET",
            headers={**self._headers(), "Prefer": "count=exact", "Range": "0-0"},
        )
        _, headers = self._send(request, f"COUNT {table}")
        return int(headers["Content-Range"].split("/")[-1])

    def update(self, table: str, filters: dict[str, str], patch: dict) -> None:
        query = urllib.parse.urlencode(filters)
        self._request("PATCH", f"/{table}?{query}", patch)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _send(self, request: urllib.request.Request, label: str) -> tuple[bytes, dict]:
        """One PostgREST call, retried past transient failures.

        Single-shot was a real exposure, not a theoretical one. On 2026-09-12
        Supabase served a run of 504s; the engine survived them because every
        CALLER wraps its call in try/except - but surviving a write is not the
        same as making it. _persist_opened_trade() logs the failure and carries
        on to announce "TRADE OPENED", so one badly-timed 504 leaves a real
        position open at the broker with no `trades` row: invisible to
        reconciliation forever, absent from the dashboard, uncounted by the
        evaluator. On the live account that is real money in a position nothing
        is tracking. Retrying is what makes the common case actually write.

        Retrying a POST is only safe because of what it writes into:
        `trades.mt5_ticket` is `not null unique` (migration 0003) and `candles`
        upserts on a unique key, so a retry of a write that silently DID land is
        rejected rather than duplicated - see the 409 branch. `signals` and
        `engine_heartbeats` have no such key and could gain a duplicate row that
        way; that is accepted deliberately, because a duplicated evaluation
        record is cosmetic and a missing trade record is not.
        """
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    if attempt > 1:
                        logger.info("%s succeeded on attempt %d", label, attempt)
                    return response.read(), dict(response.headers)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                if exc.code == 409 and attempt > 1:
                    # A unique key rejected this. On a RETRY that is the good
                    # outcome: the attempt before it did land and the gateway
                    # simply never said so. Treating it as success is what makes
                    # the retry exactly-once rather than at-least-once.
                    logger.info("%s: already applied by a previous attempt", label)
                    return b"", {}
                if exc.code not in TRANSIENT_STATUSES or attempt == MAX_ATTEMPTS:
                    raise SupabaseError(f"{label} failed: {exc.code} {detail}") from exc
                last = exc
                logger.warning("%s: %d, retrying (%d/%d)", label, exc.code, attempt, MAX_ATTEMPTS)
            except OSError as exc:
                # URLError and socket timeouts both land here (both are OSError,
                # and HTTPError is handled above). A connection that never
                # completed is the clearest possible case for trying again.
                if attempt == MAX_ATTEMPTS:
                    raise SupabaseError(f"{label} failed: {exc}") from exc
                last = exc
                logger.warning("%s: %s, retrying (%d/%d)", label, exc, attempt, MAX_ATTEMPTS)
            time.sleep(BACKOFF_SECONDS * attempt)
        raise SupabaseError(f"{label} failed after {MAX_ATTEMPTS} attempts: {last}")

    def _request(self, method: str, path: str, body, extra_headers: dict | None = None):
        headers = self._headers()
        headers.update(extra_headers or {})
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method, headers=headers)
        raw, _ = self._send(request, f"{method} {path}")
        return json.loads(raw) if raw else None
