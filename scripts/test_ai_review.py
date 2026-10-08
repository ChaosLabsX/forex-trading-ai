r"""The AI reviewer asks Opus 5.5 the way Opus 5.5 accepts, and is scored per model.

    .venv\Scripts\python.exe scripts\test_ai_review.py

No API calls: the Anthropic client and Supabase are fakes that record what they
were sent. Opus 5.5 returns a 400 for a forced tool_choice, which the Opus 5 code
used - and the loop logs a failed review and moves on, so that breakage would
have been silent: no crash, no alert, just no more reviews. These checks pin the
request to a shape the model takes, and pin what happens when no verdict comes back.

Whether the real API accepts that shape is a separate question, answered only by
calling it - this file proves the logic around the call.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import review_scoring                                                  # noqa: E402
from engine.core.interfaces.strategy import StrategyContext                       # noqa: E402
from engine.core.models import AccountState, Direction, Signal, Timeframe         # noqa: E402
from engine.plugins.ai import claude_ai_provider as provider_mod                  # noqa: E402
from engine.plugins.ai.claude_ai_provider import ClaudeAIProvider                 # noqa: E402

SIGNAL = Signal("london_breakout_v1", "EURGBP", Direction.SHORT, Timeframe.H1,
                0.85649, 0.85694, 0.85581, "London-open break SHORT of a compressed Asian range")
CONTEXT = StrategyContext("EURGBP", {}, AccountState(225.19, 455.19, 0, 0, 0, 0), [])


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def verdict_block(approved=False, confidence=0.6, rationale="stop inside the spread"):
    return types.SimpleNamespace(type="tool_use", name="submit_verdict",
                                 input={"approved": approved, "confidence": confidence, "rationale": rationale})


def reply(*blocks, stop_reason="tool_use", category=None):
    details = types.SimpleNamespace(type="refusal", category=category) if stop_reason == "refusal" else None
    return types.SimpleNamespace(content=list(blocks), stop_reason=stop_reason, stop_details=details)


THINKING = types.SimpleNamespace(type="thinking", thinking="")
TEXT = types.SimpleNamespace(type="text", text="Looks marginal.")


class FakeClient:
    """Stands in for anthropic.Anthropic: replays canned replies, records requests."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        return self.replies.pop(0)


def reviewer(*replies) -> tuple[ClaudeAIProvider, FakeClient]:
    p = ClaudeAIProvider(types.SimpleNamespace(anthropic_api_key="test-key-not-real"))
    p._client = FakeClient(*replies)
    return p, p._client


def raises(fn) -> str | None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - the message is what is under test
        return str(e)
    return None


class FakeSupabase:
    """trades / ai_reviews, filtered the way PostgREST would for the filters used."""

    def __init__(self, trades, reviews):
        self.tables = {"trades": trades, "ai_reviews": reviews}
        self.queries = []

    def select(self, table, filters):
        self.queries.append((table, dict(filters)))
        rows = self.tables[table]
        for column, condition in filters.items():
            if column in ("select", "order", "limit"):
                continue
            op, value = condition.split(".", 1)
            if op == "eq":
                rows = [r for r in rows if str(r.get(column)) == value]
            elif op == "in":
                wanted = set(value.strip("()").split(","))
                rows = [r for r in rows if str(r.get(column)) in wanted]
            elif op == "not" and value == "is.null":
                rows = [r for r in rows if r.get(column) is not None]
        return [dict(r) for r in rows]


def main() -> int:
    passed = []

    print("the request is one Opus 5.5 accepts")
    p, client = reviewer(reply(THINKING, verdict_block()))
    p.review_signal(SIGNAL, CONTEXT, track_record=None)
    req = client.requests[0]
    passed.append(check("model is claude-opus-5-5", req["model"], "claude-opus-5-5"))
    passed.append(check("the stored label matches the model asked", p.model_name, req["model"]))
    passed.append(check("tool_choice is auto (forced 'tool' is a 400 on 5.5)", req["tool_choice"], {"type": "auto"}))
    passed.append(check("thinking is not sent (disabled/budget are 400s on 5.5)", "thinking" in req, False))
    passed.append(check("effort pinned at high, not 5.5's medium default", req.get("output_config"), {"effort": "high"}))
    tool = req["tools"][0]
    passed.append(check("verdict tool is strict", tool.get("strict"), True))
    passed.append(check("strict schema closes extra fields", tool["input_schema"].get("additionalProperties"), False))
    passed.append(check("all three fields required", sorted(tool["input_schema"]["required"]),
                        ["approved", "confidence", "rationale"]))
    passed.append(check("prompt asks for the tool call by name", "calling\nsubmit_verdict" in req["messages"][0]["content"]
                        or "calling submit_verdict" in req["messages"][0]["content"], True))
    passed.append(check("max_tokens leaves room for thinking", req["max_tokens"] >= 16000, True))

    print("\nreading the verdict")
    p, _ = reviewer(reply(THINKING, TEXT, verdict_block(approved=True, confidence=0.71, rationale="clean break")))
    v = p.review_signal(SIGNAL, CONTEXT)
    passed.append(check("found after thinking and text blocks", (v.approved, v.confidence, v.rationale),
                        (True, 0.71, "clean break")))

    print("\nwhen no verdict comes back")
    p, client = reviewer(reply(THINKING, TEXT, stop_reason="end_turn"), reply(THINKING, verdict_block()))
    v = p.review_signal(SIGNAL, CONTEXT)
    passed.append(check("retried once, and the retry's verdict is used", (len(client.requests), v.approved), (2, False)))
    passed.append(check("the retry is the identical request", client.requests[0] == client.requests[1], True))
    p, client = reviewer(reply(TEXT, stop_reason="end_turn"), reply(TEXT, stop_reason="max_tokens"))
    err = raises(lambda: p.review_signal(SIGNAL, CONTEXT))
    passed.append(check("two empty replies raise, after exactly 2 calls",
                        (err is not None and "no verdict" in err, len(client.requests)), (True, 2)))

    print("\nwhen the model declines")
    p, client = reviewer(reply(stop_reason="refusal", category="cyber"), reply(verdict_block()))
    err = raises(lambda: p.review_signal(SIGNAL, CONTEXT))
    passed.append(check("refusal raises, naming the category", err is not None and "cyber" in err, True))
    passed.append(check("refusal is not retried", len(client.requests), 1))
    passed.append(check("no fallback model is requested", "fallbacks" in client.requests[0], False))

    print("\nscored per model")
    trades = [{"signal_id": i, "realized_pnl": pnl, "risk_amount": 1.0, "void_reason": None,
               "status": "CLOSED", "account_key": "icmarkets-live"} for i, pnl in
              [(1, 1.5), (2, -1.0), (3, -1.0), (4, 1.4), (5, -1.1)]]
    reviews = [
        {"signal_id": 1, "model": "claude-opus-5", "approved": True},
        {"signal_id": 2, "model": "claude-opus-5", "approved": False},
        {"signal_id": 3, "model": "claude-opus-4-8", "approved": True},
        {"signal_id": 4, "model": "claude-opus-5-5", "approved": True},
        {"signal_id": 5, "model": "claude-opus-5-5", "approved": False},
    ]
    db = FakeSupabase(trades, reviews)
    rec = review_scoring.compute(db, "icmarkets-live", "claude-opus-5-5")
    passed.append(check("5.5 is scored on its own 2 verdicts only", (rec.scored, rec.approved.trades_count,
                        rec.rejected.trades_count), (2, 1, 1)))
    passed.append(check("the review query filters on the model", db.queries[-1][1].get("model"), "eq.claude-opus-5-5"))
    rec = review_scoring.compute(FakeSupabase(trades, reviews), "icmarkets-live", "claude-opus-5")
    passed.append(check("Opus 5's record is unchanged by the switch", (rec.scored, rec.approved.trades_count), (2, 1)))
    rec = review_scoring.compute(FakeSupabase(trades, []), "icmarkets-live", "claude-opus-5-5")
    passed.append(check("a model with no reviews says 'not scored yet'",
                        rec.summary_for_prompt().startswith("Your past verdicts have not been scored yet"), True))

    print("\nthe loop asks for the running model's record")
    src = (Path(__file__).resolve().parent.parent / "engine" / "loop.py").read_text(encoding="utf-8")
    passed.append(check("loop passes ai_provider.model_name to compute()",
                        "self._supabase, self._account_key, self._engine.ai_provider.model_name" in src, True))
    passed.append(check("provider module exports one MODEL constant", provider_mod.MODEL, "claude-opus-5-5"))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
