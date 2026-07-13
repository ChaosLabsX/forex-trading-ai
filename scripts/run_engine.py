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
    # File handler is what makes this work under Task Scheduler, which
    # doesn't capture stdout/stderr the way a manually-redirected console
    # process does - console handler stays too, for local interactive runs.
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_dir / "engine.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
            ),
            logging.StreamHandler(),
        ],
    )

    settings = Settings()
    engine = build_engine(settings=settings)
    supabase = SupabaseClient(settings)

    if engine.broker is None or engine.market_data is None:
        raise SystemExit("broker and market_data must both be configured in config/plugins.yaml")

    EngineLoop(engine, supabase).run_forever()


if __name__ == "__main__":
    main()
