r"""Exercise infra/watchdog.ps1 against a stub Supabase. No VPS, no MT5, no secrets.

    .venv\Scripts\python.exe scripts	est_watchdog.py

The watchdog is the only thing that notices a dead engine, so when IT breaks
nothing says so - and it has now broken silently twice:

  * 2026-09-11  a recovery saved only at the end of the run, so a mid-run throw
                lost it and the all-clear repeated every 5 minutes forever.
  * 2026-09-12  `@(Invoke-RestMethod ...)` does not flatten in PS 5.1. With two
                enabled accounts the per-account loop ran once with $account
                bound to BOTH rows, queried an account named
                "icmarkets-demo icmarkets-live", and died on the unparseable
                timestamp that came back. Every run, since the live account was
                added. One alert reached Telegram naming both accounts at once;
                that was the only visible symptom.

Both were invisible to the eye and obvious to a stub. Hence this. Run it after
touching watchdog.ps1.

Every scenario asserts on the ALERTS, because alerts are the product: the
watchdog is judged on saying the true thing at the right moment, not on running.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATCHDOG = REPO / "infra" / "watchdog.ps1"
KEYS = ["icmarkets-demo", "icmarkets-live"]

# Mutated per scenario; read by the stub on every request.
MODE: dict = {"silent": set(), "hb_failures": 0}


class Stub(BaseHTTPRequestHandler):
    """Enough PostgREST to answer the two queries the watchdog makes."""

    def _json(self, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        parsed = urllib.parse.urlparse(self.path)
        if "accounts" in parsed.path:
            return self._json([{"key": k} for k in KEYS])

        if MODE["hb_failures"] != 0:
            if MODE["hb_failures"] > 0:
                MODE["hb_failures"] -= 1
            self.send_response(504)                      # what Supabase actually returned
            self.end_headers()
            self.wfile.write(b"Gateway Timeout")
            return

        query = urllib.parse.parse_qs(parsed.query)
        key = query.get("account_key", [""])[0].removeprefix("eq.")
        self.server.asked.append(key)                    # type: ignore[attr-defined]
        if key not in KEYS:
            return self._json([])                        # no such account
        age = timedelta(hours=1) if key in MODE["silent"] else timedelta(0)
        stamp = (datetime.now(timezone.utc) - age).isoformat()
        return self._json([{"created_at": stamp, "status": "running"}])

    def log_message(self, *args) -> None:
        pass


def run_watchdog(work: Path, script: Path, name: str) -> list[str]:
    """One watchdog run. Returns the alert texts it would have sent."""
    log = work / f"{name}.log"
    before = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-DryRun", "-EnvFile", str(work / ".env"),
         "-StateFile", str(work / f"{name}.json"), "-LogFile", str(log),
         "-HttpRetryDelaySec", "1"],
        capture_output=True, text=True,
    )
    after = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    return [line.split("would send: ", 1)[1]
            for line in after[len(before):].splitlines() if "would send: " in line]


def _safe(value) -> str:
    """Alert text carries emoji; a Windows console is cp1252. Print through
    ASCII rather than let a failing check die inside its own failure report."""
    return str(value).encode("ascii", "replace").decode()


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {_safe(want)}")
        print(f"         actual  : {_safe(got)}")
    return ok


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="watchdog-test-"))
    server = HTTPServer(("127.0.0.1", 0), Stub)
    server.asked = []                                    # type: ignore[attr-defined]
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    (work / ".env").write_text(
        f"SUPABASE_URL=http://127.0.0.1:{port}\nSUPABASE_SERVICE_ROLE_KEY=stub\n"
        "TELEGRAM_BOT_TOKEN=stub\nTELEGRAM_CHAT_ID=stub\n", encoding="utf-8")
    script = work / "watchdog.ps1"
    shutil.copy(WATCHDOG, script)

    passed = []
    print(f"stub Supabase on 127.0.0.1:{port}, accounts = {', '.join(KEYS)}\n")

    print("both engines healthy")
    MODE.update(silent=set(), hb_failures=0)
    server.asked.clear()                                 # type: ignore[attr-defined]
    alerts = run_watchdog(work, script, "healthy")
    passed.append(check("no alerts", alerts, []))
    # The 2026-09-12 bug in one line: it asked about an account named
    # "icmarkets-demo icmarkets-live" instead of asking about each.
    passed.append(check("queried each account separately",
                        sorted(server.asked), sorted(KEYS)))  # type: ignore[attr-defined]

    print("\ndemo engine silent for an hour, live engine fine")
    MODE.update(silent={"icmarkets-demo"}, hb_failures=0)
    first = run_watchdog(work, script, "dead")
    second = run_watchdog(work, script, "dead")
    passed.append(check("alerts about the demo engine only",
                        [a.split("/")[0].strip().split()[-1] for a in first], ["ICMARKETS-DEMO"]))
    passed.append(check("does not repeat five minutes later", second, []))

    print("\nSupabase blips once, then answers")
    MODE.update(silent=set(), hb_failures=2)             # 2 failures, 3rd attempt wins
    alerts = run_watchdog(work, script, "transient")
    passed.append(check("rides out a transient 504 silently", alerts, []))

    print("\nSupabase down for good")
    MODE.update(silent=set(), hb_failures=-1)            # -1 = fail forever
    first = run_watchdog(work, script, "outage")
    second = run_watchdog(work, script, "outage")
    passed.append(check("one BLIND alert per account", len(first), 2))
    passed.append(check("each names a single account",
                        all(sum(k.upper() in a for k in KEYS) == 1 for a in first), True))
    passed.append(check("does not repeat five minutes later", second, []))

    server.shutdown()
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    if not all(passed):
        print(f"artifacts kept: {work}")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
