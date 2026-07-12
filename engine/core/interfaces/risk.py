from __future__ import annotations

from abc import ABC, abstractmethod

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
    ) -> RiskDecision: ...
