from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.risk import RiskEngine
from engine.core.models import AccountState, ApprovedOrder, Position, PositionStatus, RiskDecision, Signal

MAX_CONCURRENT_TRADES = 2
MAX_CONSECUTIVE_STOP_LOSSES = 3
MAX_DAILY_LOSS_PCT = 3.0
TEST_MODE_LOT_SIZE = 0.01


class DefaultRiskEngine(RiskEngine):
    """TEST_MODE-driven fixed-lot sizing plus the safety rails from PLAN.md:
    max concurrent trades, a consecutive-losing-trades circuit breaker, and an
    independent max-daily-loss % circuit breaker. Live (non-TEST_MODE) sizing
    isn't built yet - that's explicitly Phase 6 scope."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate_signal(
        self,
        signal: Signal,
        account_state: AccountState,
        open_positions: list[Position],
    ) -> RiskDecision:
        open_count = sum(1 for p in open_positions if p.status == PositionStatus.OPEN)
        if open_count >= MAX_CONCURRENT_TRADES:
            return RiskDecision(approved=False, reason=f"max concurrent trades reached ({MAX_CONCURRENT_TRADES})")

        if account_state.consecutive_stop_losses_today >= MAX_CONSECUTIVE_STOP_LOSSES:
            return RiskDecision(
                approved=False,
                reason=(
                    f"circuit breaker: {account_state.consecutive_stop_losses_today} consecutive "
                    f"losing trades today (limit {MAX_CONSECUTIVE_STOP_LOSSES})"
                ),
            )

        if account_state.balance > 0:
            daily_loss_pct = -account_state.daily_pnl / account_state.balance * 100
            if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
                return RiskDecision(
                    approved=False,
                    reason=f"circuit breaker: daily loss {daily_loss_pct:.2f}% >= cap {MAX_DAILY_LOSS_PCT}%",
                )

        if not self._settings.test_mode:
            # Live sizing (e.g. % equity risk derived from stop distance) is
            # Phase 6 scope - refuse to size a live-money order until that
            # exists rather than silently reusing the demo's fixed micro lot.
            return RiskDecision(approved=False, reason="live-mode position sizing not implemented yet")

        order = ApprovedOrder(signal=signal, lot_size=TEST_MODE_LOT_SIZE, approved_by="default_risk_engine")
        return RiskDecision(approved=True, reason="within risk limits (TEST_MODE fixed lot)", order=order)
