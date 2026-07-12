from __future__ import annotations

import anthropic

from engine.config import Settings
from engine.core.interfaces.ai_provider import AIProvider
from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import AIVerdict, Signal

MODEL = "claude-sonnet-5"

_VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit your risk assessment of this candidate trade signal.",
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

    def review_signal(self, signal: Signal, context: StrategyContext) -> AIVerdict:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=512,
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "submit_verdict"},
            messages=[{"role": "user", "content": self._build_prompt(signal, context)}],
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return AIVerdict(
            approved=bool(tool_use.input["approved"]),
            confidence=float(tool_use.input["confidence"]),
            rationale=str(tool_use.input["rationale"]),
        )

    @staticmethod
    def _build_prompt(signal: Signal, context: StrategyContext) -> str:
        account = context.account_state
        risk_distance = abs(signal.entry_price - signal.stop_loss)
        reward_distance = abs(signal.take_profit - signal.entry_price)
        reward_risk_text = f"{reward_distance / risk_distance:.2f}" if risk_distance else "n/a"

        return f"""You are a secondary risk reviewer for an automated forex/CFD trading
system. A rules-based strategy has produced a candidate trade. You are not
placing this trade - you are giving a second opinion that will be logged
alongside the outcome for later comparison. Be honest and skeptical; there is
no reward for rubber-stamping.

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
rationale and current account risk state, then call submit_verdict."""
