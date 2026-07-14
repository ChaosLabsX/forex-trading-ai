from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.interfaces.broker import BrokerAdapter
from engine.core.models import AccountState, Position, RiskDecision, Signal


class RiskEngine(ABC):
    """Gatekeeper between a strategy's signal and the execution engine.

    Owns position sizing, max-concurrent-trades, and circuit-breaker rules.
    A strategy proposing a signal never guarantees it gets traded.
    """

    @abstractmethod
    def validate_signal(
        self,
        signal: Signal,
        account_state: AccountState,
        open_positions: list[Position],
        broker: BrokerAdapter,
        risk_pct: float | None = None,
    ) -> RiskDecision:
        """`broker` is passed explicitly (same convention as ExecutionEngine)
        because real sizing needs live contract specs - lot step, tick value,
        margin - which are the broker's facts, not config.

        `risk_pct` is the per-(strategy, account) override from the registry;
        None means fall back to the engine's default."""
        ...
