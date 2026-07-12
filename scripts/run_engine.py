"""Phase 1 entrypoint - data feed + heartbeat, no strategy/risk/execution yet.

    python scripts/run_engine.py

Runs as a plain foreground script during local development (Ctrl+C to stop).
Gets wrapped as a Windows service only at VPS deployment (Phase 6).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.loop import EngineLoop
from engine.registry import build_engine
from engine.supabase_client import SupabaseClient


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings()
    engine = build_engine(settings=settings)
    supabase = SupabaseClient(settings)

    if engine.broker is None or engine.market_data is None:
        raise SystemExit("broker and market_data must both be configured in config/plugins.yaml")

    EngineLoop(engine, supabase).run_forever()


if __name__ == "__main__":
    main()
