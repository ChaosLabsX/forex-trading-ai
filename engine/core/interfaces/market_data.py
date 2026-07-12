from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import Candle, Tick, Timeframe


class MarketDataProvider(ABC):
    """Ticks and candles for a symbol, independent of where they come from."""

    @abstractmethod
    def get_latest_tick(self, symbol: str) -> Tick: ...

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]: ...
