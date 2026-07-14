"""The engine's entrypoint - full pipeline (data feed, strategy, risk,
execution, AI review, command handling).

    python scripts/run_engine.py

Runs standalone during local development (Ctrl+C to stop) and, on the VPS,
via a Task Scheduler "at logon" trigger (see infra/setup-scheduled-tasks.ps1)
rather than a Windows service - MT5's Python bridge needs an interactive
desktop session, which a Session-0 service doesn't have.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.loop import EngineLoop
from engine.registry import build_engine
from engine.supabase_client import SupabaseClient


def main() -> None:
    # Verify TLS against the OS trust store, not OpenSSL's bundled CAs, and do
    # it before anything opens a connection. On the VPS, api.telegram.org's
    # certificate chain validates under Windows' own verifier (confirmed via
    # .NET SslStream: zero policy errors) but not under Python's OpenSSL
    # default context, which can't build the same path and reports
    # "self-signed certificate in certificate chain". truststore delegates
    # verification to Windows' verifier - the one that already trusts this
    # chain - so verification stays fully on, just sourced from the store that
    # works. No-op where OpenSSL already succeeds (e.g. Supabase, Anthropic).
    import truststore

    truststore.inject_into_ssl()

    # Make console logging tolerant of non-ASCII (emoji in trade alerts) so a
    # legacy code-page console can never turn a notification into an encoding
    # error. The rotating file handler is already UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    settings = Settings()

    # File handler is what makes this work under Task Scheduler, which
    # doesn't capture stdout/stderr the way a manually-redirected console
    # process does - console handler stays too, for local interactive runs.
    #
    # One log file PER ACCOUNT: the demo and live engines are separate processes
    # on the same box, and RotatingFileHandler is not safe across processes -
    # sharing one file would interleave writes and corrupt on rotation.
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_dir / f"engine-{settings.account_key}.log",
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )
    engine = build_engine(settings=settings)
    supabase = SupabaseClient(settings)

    if engine.broker is None or engine.market_data is None:
        raise SystemExit("broker and market_data must both be configured in config/plugins.yaml")

    EngineLoop(engine, supabase, settings).run_forever()


if __name__ == "__main__":
    main()
