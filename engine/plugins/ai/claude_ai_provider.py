from __future__ import annotations

import logging

import anthropic

from engine.config import Settings
from engine.core.interfaces.ai_provider import AIProvider
from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import AIVerdict, Signal

logger = logging.getLogger("engine.ai.claude")

# Opus for the review: this is a judgement call on a real trade, and the whole
# point of shadow mode is to build a track record worth trusting later - a
# cheaper model would make that record less meaningful. Reviews only run when a
# signal actually fires (rare), so the cost is negligible.
#
# Changing this starts a new track record: review_scoring scores each model on
# its own verdicts only, so the new reviewer is never shown its predecessor's
# results as if they were its own.
MODEL = "claude-opus-5-5"

# Opus 5.5 defaults to "medium"; Opus 5 ran this review at "high", its default.
# Pinned so the upgrade doesn't quietly lower the thinking behind a real-money
# opinion. Cost is not the constraint here - reviews fire a few times a week.
EFFORT = "high"

# A missing verdict is retried once (see review_signal), then given up on.
ATTEMPTS = 2

_VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit your risk assessment of this candidate trade signal.",
    # Opus 5.5 rejects a forced tool_choice, so the call is requested in the
    # prompt instead; strict keeps the arguments to this schema when it comes.
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "Whether this trade looks reasonable to take, given the context provided.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in this assessment, from 0.0 to 1.0.",
            },
            "rationale": {
                "type": "string",
                "description": "2-3 sentence explanation of the verdict.",
            },
        },
        "required": ["approved", "confidence", "rationale"],
        "additionalProperties": False,
    },
}


class ClaudeAIProvider(AIProvider):
    """Shadow-mode reviewer (Phase 5): logs an opinion, never blocks
    execution on its own - RiskEngine's decision is what actually gates a
    trade until this has a track record to be trusted."""

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set in .env")
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @property
    def model_name(self) -> str:
        return MODEL

    def review_signal(
        self, signal: Signal, context: StrategyContext, track_record: str | None = None
    ) -> AIVerdict:
        """Raises when no verdict comes back. The caller logs that and moves on;
        a missing review never touches the trade, which has already been decided.

        No refusal fallback to another model, deliberately. A decline here costs
        one missing log row, while a fallback would put a different model's
        opinion under this model's name in the record being scored."""
        prompt = self._build_prompt(signal, context, track_record)
        for attempt in range(1, ATTEMPTS + 1):
            response = self._client.messages.create(
                model=MODEL,
                # Thinking is always on for Opus 5.5 and counts against
                # max_tokens. The verdict itself is ~150 tokens; this leaves room
                # to reason and still caps a runaway response. (At 512 under Opus
                # 5, the thinking ate the whole budget and every review failed.)
                max_tokens=16000,
                output_config={"effort": EFFORT},
                tools=[_VERDICT_TOOL],
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason == "refusal":
                details = response.stop_details
                raise RuntimeError(
                    f"{MODEL} declined to review {signal.symbol} "
                    f"(category {getattr(details, 'category', None)})"
                )
            tool_use = next(
                (b for b in response.content if b.type == "tool_use" and b.name == _VERDICT_TOOL["name"]),
                None,
            )
            if tool_use is not None:
                return AIVerdict(
                    approved=bool(tool_use.input["approved"]),
                    confidence=float(tool_use.input["confidence"]),
                    rationale=str(tool_use.input["rationale"]),
                )
            logger.warning(
                "%s gave no verdict for %s (attempt %d/%d, stop_reason=%s)",
                MODEL, signal.symbol, attempt, ATTEMPTS, response.stop_reason,
            )
        raise RuntimeError(f"{MODEL} gave no verdict for {signal.symbol} after {ATTEMPTS} attempts")

    @staticmethod
    def _build_prompt(
        signal: Signal, context: StrategyContext, track_record: str | None = None
    ) -> str:
        account = context.account_state
        risk_distance = abs(signal.entry_price - signal.stop_loss)
        reward_distance = abs(signal.take_profit - signal.entry_price)
        reward_risk_text = f"{reward_distance / risk_distance:.2f}" if risk_distance else "n/a"
        record_section = f"\n\n{track_record}\n" if track_record else ""

        return f"""You are a secondary risk reviewer for an automated forex/CFD trading
system. A rules-based strategy has produced a candidate trade. You are not
placing this trade - you are giving a second opinion that will be logged
alongside the outcome for later comparison. Be honest and skeptical; there is
no reward for rubber-stamping.

Note what "no reward for rubber-stamping" means concretely here: because your
verdict does not gate execution, every trade you reject is taken anyway and its
result recorded. Approving everything is therefore not a safe default - it is
the one behaviour guaranteed to prove, on the record, that your review adds
nothing.{record_section}

Signal:
- Strategy: {signal.strategy_name}
- Symbol: {signal.symbol}
- Direction: {signal.direction.value}
- Timeframe: {signal.timeframe.value}
- Entry: {signal.entry_price}
- Stop-loss: {signal.stop_loss}
- Take-profit: {signal.take_profit}
- Reward:risk ratio: {reward_risk_text}
- Strategy's own reasoning: {signal.reason}

Account/risk context:
- Balance: {account.balance}
- Equity: {account.equity}
- Open positions: {account.open_positions_count}
- Daily P&L so far: {account.daily_pnl}
- Consecutive losing trades today: {account.consecutive_stop_losses_today}

Assess whether this specific trade looks reasonable given the technical
rationale and current account risk state, then give your verdict by calling
submit_verdict."""
