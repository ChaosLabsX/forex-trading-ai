from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.interfaces.broker import BrokerAdapter
from engine.core.models import ApprovedOrder, Position, Tick


class ExecutionEngine(ABC):
    """Turns a risk-approved order into broker actions and manages it while open.

    Takes the broker as an explicit argument rather than holding one - talks to
    the BrokerAdapter interface, never a concrete broker, and stays a plain
    Settings-only plugin like every other subsystem (the engine loop already
    holds the configured broker and passes it through).
    """

    @abstractmethod
    def execute(self, approved_order: ApprovedOrder, broker: BrokerAdapter) -> Position: ...

    @abstractmethod
    def manage_open_position(
        self, position: Position, latest_tick: Tick, broker: BrokerAdapter
    ) -> Position | None:
        """Called per tick for open positions; handles breakeven/trailing. Returns
        the updated position, or None if unchanged."""
        ...
