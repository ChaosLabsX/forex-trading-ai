"""Risk-based position sizing: turn "risk R% of equity" into a lot size.

Deliberately pure - no MT5, no DB, no I/O - because this is the function that
decides how much real money is on the line, and it must be exhaustively testable
without a broker attached.

The whole job: given equity, a risk budget, and the distance to the stop, find
the largest lot size whose loss-at-stop does not exceed the budget, expressed in
increments the broker will actually accept.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolLimits:
    """Broker facts about one symbol. Read from MT5 at runtime, never
    hardcoded per strategy - contract specs are the broker's to change."""

    volume_min: float
    volume_max: float
    volume_step: float
    value_per_price_per_lot: float  # account currency per 1.0 price move, 1.0 lot


@dataclass(frozen=True)
class SizingResult:
    lots: float | None  # None means "do not trade"
    reason: str
    risk_amount: float | None  # currency actually at risk at this lot size


def _decimals(step: float) -> int:
    """Decimal places implied by a lot step (0.01 -> 2), so the volume we send
    is exactly representable rather than 0.30000000000000004."""
    text = f"{step:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def smallest_placeable_lots(limits: SymbolLimits) -> SizingResult:
    """The smallest volume THIS broker accepts for THIS symbol.

    What the demo lab actually needs from a lot size is only that it be
    placeable: the lab measures edge in R, and R = pnl / risk_amount is
    invariant to size, so a bigger or smaller position changes no statistic.

    A hardcoded 0.01 is an FX convention, not a universal minimum. Index CFDs
    carry a larger volume_min, and MT5 rejects anything under it outright
    (retcode 10014 INVALID_VOLUME) - so those instruments could fire signals
    forever and never record a single trade, shrinking a strategy's real
    universe below its declared one without a word. Found live on MidDE50.
    Contract specs are the broker's to state, exactly as size_position()
    already treats them on the live path."""
    if limits.volume_step <= 0:
        return SizingResult(None, "broker reported no volume step for this symbol", None)
    if limits.volume_min <= 0:
        return SizingResult(None, "broker reported no minimum volume for this symbol", None)
    lots = round(limits.volume_min, _decimals(limits.volume_step))
    return SizingResult(lots, f"broker minimum {lots} lot", None)


def size_position(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    limits: SymbolLimits,
) -> SizingResult:
    if equity <= 0:
        return SizingResult(None, "account equity is zero or negative", None)
    if risk_pct <= 0:
        return SizingResult(None, f"risk_pct {risk_pct} is not positive", None)

    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        # Without a stop distance the risk is unbounded - never guess one.
        return SizingResult(None, "stop distance is zero - cannot bound risk", None)
    if limits.value_per_price_per_lot <= 0:
        return SizingResult(None, "broker reported no tick value for this symbol", None)
    if limits.volume_step <= 0:
        return SizingResult(None, "broker reported no volume step for this symbol", None)

    budget = equity * risk_pct / 100.0
    loss_per_lot = stop_distance * limits.value_per_price_per_lot
    raw_lots = budget / loss_per_lot

    # Round DOWN to the broker's step, always. Rounding up would risk more than
    # the budget allows - the one direction this must never err in.
    steps = math.floor(raw_lots / limits.volume_step + 1e-9)
    lots = round(steps * limits.volume_step, _decimals(limits.volume_step))

    if lots < limits.volume_min:
        return SizingResult(
            None,
            (
                f"risk budget ${budget:.2f} only affords {raw_lots:.4f} lots, below the broker "
                f"minimum {limits.volume_min} - stop is too wide for this equity"
            ),
            None,
        )
    if lots > limits.volume_max:
        lots = limits.volume_max

    risk_amount = lots * loss_per_lot
    return SizingResult(
        lots,
        f"risking {risk_pct:.2f}% of ${equity:,.2f} (${risk_amount:.2f}) at {lots} lots",
        risk_amount,
    )
