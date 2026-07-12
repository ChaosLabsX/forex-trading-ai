from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.interfaces.execution import ExecutionEngine
from engine.core.models import ApprovedOrder, Position, Tick


class DefaultExecutionEngine(ExecutionEngine):
    """v1: places the order with stop-loss/take-profit set at entry and leaves
    them alone - MT5 enforces SL/TP natively at the broker/terminal level, so
    the position stays protected even if this process is down. Breakeven-move
    and trailing (from the strategy's spec in PLAN.md) are a deferred
    enhancement, not implemented in manage_open_position() yet."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def execute(self, approved_order: ApprovedOrder, broker: BrokerAdapter) -> Position:
        signal = approved_order.signal
        return broker.place_order(
            symbol=signal.symbol,
            direction=signal.direction,
            lot_size=approved_order.lot_size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

    def manage_open_position(
        self, position: Position, latest_tick: Tick, broker: BrokerAdapter
    ) -> Position | None:
        return None
