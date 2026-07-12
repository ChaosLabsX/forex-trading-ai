from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from engine.config import Settings


class SupabaseError(RuntimeError):
    pass


class SupabaseClient:
    """Minimal PostgREST wrapper - no supabase-py dependency needed for the
    handful of insert/upsert calls the engine makes."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        self._base = settings.supabase_url.rstrip("/") + "/rest/v1"
        self._key = settings.supabase_service_role_key

    def insert(self, table: str, rows: list[dict]) -> None:
        self._request("POST", f"/{table}", rows)

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        query = urllib.parse.urlencode({"on_conflict": on_conflict})
        self._request(
            "POST",
            f"/{table}?{query}",
            rows,
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )

    def _request(self, method: str, path: str, body: list[dict], extra_headers: dict | None = None) -> None:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        data = json.dumps(body).encode()
        request = urllib.request.Request(self._base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise SupabaseError(f"{method} {path} failed: {exc.code} {exc.read().decode()}") from exc
