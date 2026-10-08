r"""One real AI review, to prove the reviewer works on this machine: key, library, model.

    .venv\Scripts\python.exe scripts\check_ai_review.py

Sends the most recent live signal through ClaudeAIProvider exactly as the engine
does, and prints the verdict, tokens and cost. Writes nothing - no ai_reviews row,
no trade. Costs about two cents.

Why it exists: the reviewer never gates a trade, so when it breaks nothing
announces it - the engine logs "AI review failed" and carries on. On 2026-10-08 the
key in one .env belonged to an Anthropic account with no credit, and the only way
to see it was to make a call. This is that call.

The account figures in the prompt are placeholders, so read the result as "a
verdict came back", not as an opinion on that trade.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from engine.config import Settings                                                 # noqa: E402
from engine.core.interfaces.strategy import StrategyContext                       # noqa: E402
from engine.core.models import AccountState, Direction, Signal, Timeframe         # noqa: E402
from engine.plugins.ai.claude_ai_provider import ClaudeAIProvider                 # noqa: E402
from engine.supabase_client import SupabaseClient                                 # noqa: E402

# $ per million tokens (input, output)
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0)}


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")
    key = settings.anthropic_api_key or ""
    print(f"anthropic library {anthropic.__version__}; key in .env ends with ...{key[-4:] or '(none)'}")

    rows = SupabaseClient(settings).select(
        "signals",
        {"account_key": "eq.icmarkets-live", "fired": "eq.true", "order": "created_at.desc", "limit": "1"},
    )
    if not rows:
        print("FAIL: no live signal in the database to review")
        return 1
    row = rows[0]
    signal = Signal(row["strategy_name"], row["symbol"], Direction(row["direction"]), Timeframe(row["timeframe"]),
                    row["entry_price"], row["stop_loss"], row["take_profit"], row["reason"], row.get("metadata") or {})
    context = StrategyContext(row["symbol"], {}, AccountState(0, 0, 0, 0, 0, 0), [])
    print(f"reviewing signal {row['id']}: {row['symbol']} {row['direction']} from {row['created_at'][:16]} UTC")

    reviewer = ClaudeAIProvider(settings)
    calls = []
    create = reviewer._client.messages.create

    def recording_create(**request):
        response = create(**request)
        calls.append(response)
        return response

    reviewer._client.messages.create = recording_create
    started = time.time()
    try:
        verdict = reviewer.review_signal(signal, context)
    except anthropic.AuthenticationError:
        print("FAIL: the API key in .env was refused - wrong, or deleted in the Claude Console")
        return 1
    except anthropic.APIStatusError as e:
        if "credit balance" in str(e):
            print("FAIL: the Anthropic account behind this key has no credit - "
                  "check the key matches the account in the Claude Console")
        else:
            print(f"FAIL: API error {e.status_code}: {e.message}")
        return 1
    except Exception as e:  # noqa: BLE001 - a diagnostic reports whatever went wrong
        print(f"FAIL: {e}")
        return 1

    cost = 0.0
    for response in calls:
        price_in, price_out = PRICES.get(response.model, (0.0, 0.0))
        cost += response.usage.input_tokens * price_in / 1e6 + response.usage.output_tokens * price_out / 1e6
    model = calls[-1].model if calls else reviewer.model_name
    print(f"\nOK: {model} returned a verdict in {time.time() - started:.0f}s "
          f"({len(calls)} call(s), about ${cost:.3f})")
    print(f"   approved={verdict.approved}  confidence={verdict.confidence:.2f}")
    print(f"   {verdict.rationale}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
