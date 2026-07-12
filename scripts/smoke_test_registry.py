"""Proves the config-driven plugin registry works end-to-end without needing
any external account (MT5, Supabase, Telegram). Run from the repo root:

    python scripts/smoke_test_registry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.models import NotificationEvent
from engine.registry import build_engine


def main() -> None:
    engine = build_engine(settings=Settings(test_mode=True))

    assert engine.notifications, "expected at least the console notifier from config/plugins.yaml"
    for notifier in engine.notifications:
        notifier.notify(
            NotificationEvent(
                event_type="smoke_test",
                message="Registry loaded and ran a real plugin end-to-end.",
            )
        )

    unimplemented = [
        name
        for name, value in [
            ("broker", engine.broker),
            ("market_data", engine.market_data),
            ("risk_engine", engine.risk_engine),
            ("execution_engine", engine.execution_engine),
            ("news_provider", engine.news_provider),
            ("ai_provider", engine.ai_provider),
        ]
        if value is None
    ]
    print(f"Not yet implemented (expected at Phase 0): {unimplemented}")
    print(f"Strategies loaded: {[s.name for s in engine.strategies]}")
    print("OK")


if __name__ == "__main__":
    main()
