from __future__ import annotations

import logging

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.interfaces.execution import ExecutionEngine
from engine.core.models import ApprovedOrder, Direction, Position, Tick

logger = logging.getLogger("engine.execution")

# Don't send a modify for a stop improvement smaller than this fraction of the
# trade's initial risk - avoids spamming the broker (and "modify to ~the same
# value" rejections / a flood of notifications) as price ticks around. The
# breakeven jump is ~1R so it always clears this; only fine-grained trailing is
# throttled by it.
MIN_STEP_R = 0.25


class DefaultExecutionEngine(ExecutionEngine):
    """Places orders with SL/TP at entry (MT5 enforces them natively, so a
    position stays protected even if this process is down) and, while a position
    is open, ratchets the stop toward profit:

      - once price reaches ``breakeven_at_r`` in profit, the stop moves to entry,
        so the trade can no longer turn into a loss;
      - once past ``trail_start_r``, the stop trails ``trail_distance_r`` behind
        price, locking in progressively more gain.

    The stop is only ever moved in the profit-locking direction, never loosened
    - so even a miscalibrated call (e.g. after a mid-trade restart, see below)
    can only protect more, never risk more. All thresholds are in R (the trade's
    initial risk), configured on ``Settings``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # position id -> initial risk distance (|entry - original stop|), captured
        # the first time the position is seen. On a mid-trade engine restart this
        # cache is empty and risk is re-derived from the current stop: if that
        # stop was already at breakeven the derived risk is ~0 and management
        # simply stops for that trade (it stays protected, just won't trail
        # further). Deliberate, documented trade-off - never unsafe because the
        # stop is never loosened.
        self._initial_risk: dict[str, float] = {}

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
        if not self._settings.trail_enabled:
            return None
        if position.stop_loss is None:
            return None  # nothing to reason about without a protective stop

        risk = self._initial_risk.get(position.id)
        if risk is None:
            risk = abs(position.entry_price - position.stop_loss)
            if risk <= 0:
                return None
            self._initial_risk[position.id] = risk

        is_long = position.direction == Direction.LONG
        # exit-side price: a long is closed at the bid, a short at the ask
        price = latest_tick.bid if is_long else latest_tick.ask
        profit = (price - position.entry_price) if is_long else (position.entry_price - price)
        r = profit / risk

        desired = self._desired_stop(position, price, risk, r, is_long)
        if desired is None:
            return None

        current = position.stop_loss
        improvement = (desired - current) if is_long else (current - desired)
        if improvement <= MIN_STEP_R * risk:
            return None  # too small to bother - and, being one-directional, never loosens

        try:
            updated = broker.modify_position(position.id, stop_loss=desired)
        except Exception:
            logger.exception("failed to modify stop for position %s", position.id)
            return None

        logger.info(
            "stop moved: %s %s -> %s (at %.2fR profit)", position.symbol, position.id, desired, r
        )
        return updated

    def _desired_stop(
        self, position: Position, price: float, risk: float, r: float, is_long: bool
    ) -> float | None:
        """The stop we'd like given how far into profit the trade is, or None to
        leave it where it is."""
        s = self._settings
        if r >= s.trail_start_r:
            offset = s.trail_distance_r * risk
            return price - offset if is_long else price + offset
        if r >= s.breakeven_at_r:
            return position.entry_price  # move to breakeven
        return None
