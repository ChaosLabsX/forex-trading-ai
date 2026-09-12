r"""Does a Supabase wobble lose a write?

    .venv\Scripts\python.exe scripts\test_supabase_retry.py

On 2026-09-12 Supabase served a run of 504s. The engine survived them - every
caller wraps its call - but surviving a write is not making it. The dangerous
one is _persist_opened_trade(): it logged the failure and carried on to announce
"TRADE OPENED", so a badly-timed 504 would leave a real position open at the
broker with no `trades` row. Invisible to reconciliation forever, absent from
the dashboard, uncounted by the evaluator - on the live account, real money in a
position nothing is tracking.

Runs the real SupabaseClient against a stub PostgREST. Asserts the write
actually lands, that a permanent failure still raises rather than passing
silently, and - the subtle one - that retrying a write which secretly DID land
does not write it twice.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.supabase_client import SupabaseClient, SupabaseError  # noqa: E402

MODE: dict = {"fail": 0, "status": 504}
STORE: list[dict] = []


class Stub(BaseHTTPRequestHandler):
    def _respond(self, code: int, body: bytes = b"[]", extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _drain(self) -> bytes:
        """Read the request body even when rejecting it. Leaving it unread makes
        the NEXT request fail with a connection abort, which quietly turns a
        '504' test into a 'connection reset' test - both retry, so it passes
        while measuring the wrong thing."""
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _maybe_fail(self) -> bool:
        if MODE["fail"] == 0:
            return False
        if MODE["fail"] > 0:
            MODE["fail"] -= 1
        if MODE["status"] == "landed":
            # The write APPLIED and the gateway then timed out telling us. The
            # nastiest case: a naive retry duplicates the row.
            self._apply()
            self._respond(504, b'{"message":"Gateway Timeout"}')
            return True
        self._drain()
        self._respond(MODE["status"], b'{"message":"Gateway Timeout"}')
        return True

    def _apply(self) -> None:
        for row in json.loads(self._drain() or b"[]"):
            if any(r["mt5_ticket"] == row["mt5_ticket"] for r in STORE):
                raise KeyError("duplicate")
            STORE.append(row)

    def do_POST(self) -> None:  # noqa: N802
        if self._maybe_fail():
            return
        try:
            self._apply()
        except KeyError:
            # What `trades.mt5_ticket text not null unique` does in Postgres.
            return self._respond(409, b'{"code":"23505","message":"duplicate key"}')
        self._respond(201)

    def do_GET(self) -> None:  # noqa: N802
        if self._maybe_fail():
            return
        if "Range" in self.headers or "count=exact" in (self.headers.get("Prefer") or ""):
            return self._respond(200, b"[]", {"Content-Range": f"0-0/{len(STORE)}"})
        self._respond(200, json.dumps(STORE).encode())

    def log_message(self, *a) -> None:
        pass


def check(label: str, got, want) -> bool:
    sys.stdout.flush()
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class FakeSettings:
        supabase_url = f"http://127.0.0.1:{port}"
        supabase_service_role_key = "stub"

    client = SupabaseClient(FakeSettings())
    row = {"mt5_ticket": "555001", "symbol": "EURUSD", "status": "OPEN"}
    passed = []

    print("a trade insert through two 504s (what Supabase actually did)")
    STORE.clear()
    MODE.update(fail=2, status=504)
    raised = None
    try:
        client.insert("trades", [row])
    except Exception as exc:
        raised = exc
    passed.append(check("did not raise", type(raised).__name__, "NoneType"))
    passed.append(check("the trade row was actually written", len(STORE), 1))

    print("\na 504 on a write that had SECRETLY landed")
    STORE.clear()
    MODE.update(fail=1, status="landed")
    raised = None
    try:
        client.insert("trades", [row])
    except Exception as exc:
        raised = exc
    passed.append(check("did not raise", type(raised).__name__, "NoneType"))
    passed.append(check("written exactly once, not twice", len(STORE), 1))

    print("\nSupabase down for good")
    STORE.clear()
    MODE.update(fail=-1, status=504)
    raised = None
    try:
        client.insert("trades", [row])
    except Exception as exc:
        raised = exc
    passed.append(check("raises so the caller can alert", type(raised).__name__, "SupabaseError"))

    print("\na 400 - a bad request, not a busy one")
    STORE.clear()
    MODE.update(fail=-1, status=400)
    calls_before = len(STORE)
    raised = None
    try:
        client.select("trades", {"status": "eq.OPEN"})
    except Exception as exc:
        raised = exc
    passed.append(check("raises immediately, no pointless retries",
                        type(raised).__name__, "SupabaseError"))

    print("\nreads recover too")
    STORE.clear()
    STORE.append(row)
    MODE.update(fail=2, status=503)
    passed.append(check("select rides out a wobble", len(client.select("trades", {})), 1))
    MODE.update(fail=2, status=503)
    passed.append(check("count rides out a wobble", client.count("trades", {}), 1))

    server.shutdown()
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
