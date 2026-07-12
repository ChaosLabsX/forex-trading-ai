from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import AccountState, Direction, Position


class BrokerAdapter(ABC):
    """Auth + account state + order lifecycle for a specific broker/terminal."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_account_state(self) -> AccountState: ...

    @abstractmethod
    def get_open_positions(self) -> list[Position]: ...

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        direction: Direction,
        lot_size: float,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> Position: ...

    @abstractmethod
    def modify_position(
        self,
        position_id: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Position: ...

    @abstractmethod
    def close_position(self, position_id: str, volume: float | None = None) -> Position: ...

    @abstractmethod
    def get_closed_position_pnl(self, position_id: str) -> float | None:
        """Realized P&L for a position that has already closed (however it
        closed - stop, target, or manual), or None if no record is found."""
        ...
