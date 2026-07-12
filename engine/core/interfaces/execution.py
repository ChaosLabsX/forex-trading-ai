from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import ApprovedOrder, Position, Tick


class ExecutionEngine(ABC):
    """Turns a risk-approved order into broker actions and manages it while open.

    Talks to the BrokerAdapter interface, never to a concrete broker directly.
    """

    @abstractmethod
    def execute(self, approved_order: ApprovedOrder) -> Position: ...

    @abstractmethod
    def manage_open_position(self, position: Position, latest_tick: Tick) -> Position | None:
        """Called per tick for open positions; handles breakeven/trailing. Returns
        the updated position, or None if unchanged."""
        ...
