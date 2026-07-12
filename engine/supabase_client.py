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

    def update(self, table: str, filters: dict[str, str], patch: dict) -> None:
        query = urllib.parse.urlencode(filters)
        self._request("PATCH", f"/{table}?{query}", patch)

    def _request(self, method: str, path: str, body, extra_headers: dict | None = None):
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise SupabaseError(f"{method} {path} failed: {exc.code} {exc.read().decode()}") from exc
