from __future__ import annotations

import logging

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.interfaces.risk import RiskEngine
from engine.core.models import AccountState, ApprovedOrder, Position, PositionStatus, RiskDecision, Signal
from engine.sizing import size_position

logger = logging.getLogger("engine.risk")

MAX_CONCURRENT_TRADES = 2
MAX_CONSECUTIVE_STOP_LOSSES = 3
MAX_DAILY_LOSS_PCT = 3.0
TEST_MODE_LOT_SIZE = 0.01


class DefaultRiskEngine(RiskEngine):
    """Safety rails plus sizing.

    Rails first, always: max concurrent trades, a consecutive-losing-trades
    circuit breaker, and an independent max-daily-loss % breaker - all computed
    from real MT5 deal history, not estimates.

    Then sizing, which depends on TEST_MODE:
      * TEST_MODE=true  -> fixed micro lot, for the demo lab. Deliberately
        ignores equity: the lab is measuring a strategy's edge in R, not
        compounding an account.
      * TEST_MODE=false -> risk-based sizing from stop distance (engine/sizing.py),
        clamped to the broker's contract specs and checked against free margin.

    TEST_MODE is NOT a safety guard for live trading - Settings.live_trading_enabled
    is (enforced in engine/gating.py, before a signal ever reaches this class).
    See docs/going-live.md.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate_signal(
        self,
        signal: Signal,
        account_state: AccountState,
        open_positions: list[Position],
        broker: BrokerAdapter,
        risk_pct: float | None = None,
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

        if self._settings.test_mode:
            order = ApprovedOrder(signal=signal, lot_size=TEST_MODE_LOT_SIZE, approved_by="default_risk_engine")
            return RiskDecision(approved=True, reason="within risk limits (TEST_MODE fixed lot)", order=order)

        return self._size_live(signal, account_state, broker, risk_pct)

    def _size_live(
        self, signal: Signal, account_state: AccountState, broker: BrokerAdapter, risk_pct: float | None
    ) -> RiskDecision:
        # A per-strategy override can lower risk but never raise it past the
        # account-wide ceiling - one bad row must not become an outsized bet.
        effective = risk_pct if risk_pct is not None else self._settings.default_risk_pct
        if effective > self._settings.max_risk_pct:
            logger.warning(
                "risk_pct %.2f exceeds max_risk_pct %.2f - clamping", effective, self._settings.max_risk_pct
            )
            effective = self._settings.max_risk_pct

        try:
            limits = broker.get_symbol_limits(signal.symbol)
        except Exception:
            logger.exception("failed to read symbol limits for %s", signal.symbol)
            return RiskDecision(approved=False, reason="could not read contract specs - refusing to size blind")
        if limits is None:
            return RiskDecision(approved=False, reason=f"broker knows no symbol {signal.symbol}")

        result = size_position(
            equity=account_state.equity,
            risk_pct=effective,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            limits=limits,
        )
        if result.lots is None:
            return RiskDecision(approved=False, reason=f"not sized: {result.reason}")

        # Margin check: sizing bounds the LOSS, not the capital committed. A
        # correctly-sized trade can still be unaffordable.
        try:
            margin = broker.calc_margin(signal.symbol, signal.direction, result.lots, signal.entry_price)
        except Exception:
            logger.exception("margin calculation failed for %s", signal.symbol)
            margin = None
        if margin is None:
            return RiskDecision(approved=False, reason="could not calculate margin - refusing to trade blind")

        free_margin = account_state.equity - account_state.margin_used
        cap = free_margin * self._settings.max_margin_use_pct / 100.0
        if margin > cap:
            return RiskDecision(
                approved=False,
                reason=(
                    f"margin ${margin:,.2f} for {result.lots} lots exceeds {self._settings.max_margin_use_pct:.0f}% "
                    f"of free margin (${cap:,.2f})"
                ),
            )

        order = ApprovedOrder(signal=signal, lot_size=result.lots, approved_by="default_risk_engine")
        return RiskDecision(approved=True, reason=result.reason, order=order)
