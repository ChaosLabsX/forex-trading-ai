from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Tick:
    symbol: str
    time: datetime
    bid: float
    ask: float


@dataclass(frozen=True)
class Signal:
    strategy_name: str
    symbol: str
    direction: Direction
    timeframe: Timeframe
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovedOrder:
    signal: Signal
    lot_size: float
    approved_by: str


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    order: ApprovedOrder | None = None


@dataclass
class Position:
    id: str
    symbol: str
    direction: Direction
    lot_size: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    status: PositionStatus
    opened_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float | None = None


@dataclass(frozen=True)
class AccountState:
    balance: float
    equity: float
    margin_used: float
    open_positions_count: int
    daily_pnl: float
    consecutive_stop_losses_today: int


@dataclass(frozen=True)
class NewsEvent:
    title: str
    time: datetime
    currency: str
    impact: str  # "low" | "medium" | "high"


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    message: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AIVerdict:
    approved: bool
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ClosedTradePnl:
    """Realized result of a closed position, split so a win can be shown before
    fees and a loss shown all-in. Commission/swap are the broker's own signed
    values (commission is normally negative; swap can be either)."""

    gross_profit: float  # market P&L only, before any costs
    commission: float
    swap: float

    @property
    def fees(self) -> float:
        return self.commission + self.swap

    @property
    def net(self) -> float:
        return self.gross_profit + self.commission + self.swap
