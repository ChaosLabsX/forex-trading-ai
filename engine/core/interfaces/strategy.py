from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.core.models import AccountState, Candle, Position, Signal, Timeframe


@dataclass(frozen=True)
class StrategyContext:
    symbol: str
    candles_by_timeframe: dict[Timeframe, list[Candle]]
    account_state: AccountState
    open_positions: list[Position]


class StrategyPlugin(ABC):
    """A swappable trading idea: market context in, at most one candidate signal out.

    The engine never inspects a strategy's internals - it only calls evaluate().
    Indicator-based, SMC/ICT, AI-assisted, and ML strategies all implement this
    same contract.
    """

    name: str
    required_timeframes: tuple[Timeframe, ...]
    instruments: tuple[str, ...]

    @abstractmethod
    def evaluate(self, context: StrategyContext) -> Signal | None: ...
