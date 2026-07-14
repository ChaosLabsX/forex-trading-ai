from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import AccountState, ClosedTradePnl, Direction, Position


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
        """Net realized P&L (gross + commission + swap) for a position that has
        already closed, or None if no record is found."""
        ...

    @abstractmethod
    def get_symbol_limits(self, symbol: str):
        """Live contract specs (min/max/step volume + tick value) as a
        `engine.sizing.SymbolLimits`, or None if the symbol is unknown. Read at
        runtime, never hardcoded - these are the broker's to change."""
        ...

    @abstractmethod
    def calc_margin(self, symbol: str, direction: Direction, lots: float, price: float) -> float | None:
        """Margin the broker would require for this order, or None if it can't
        be calculated. Used to refuse trades that would over-commit the account."""
        ...

    @abstractmethod
    def get_price_value_per_lot(self, symbol: str) -> float | None:
        """Account-currency value of a 1.0 price move for 1.0 lot, or None if the
        symbol is unknown. Lets the engine record what a trade actually risked
        (risk_amount) at open, which is what makes R-multiples computable later."""
        ...

    @abstractmethod
    def get_closed_position_breakdown(self, position_id: str) -> ClosedTradePnl | None:
        """Realized result split into gross profit / commission / swap, or None
        if no record is found. Lets a win be reported before fees and a loss
        all-in."""
        ...
