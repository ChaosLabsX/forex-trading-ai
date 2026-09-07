from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import Candle, Tick, Timeframe


class SymbolUnavailableError(RuntimeError):
    """This account's server has no such symbol.

    Separate from an ordinary fetch failure because the right response is the
    opposite one: stop asking, rather than retry. Availability is a property of
    the SERVER, while a strategy's instrument list is global - so a symbol can
    be perfectly valid on the demo server and absent on the live one, and no
    number of retries will conjure it.
    """


class MarketDataProvider(ABC):
    """Ticks and candles for a symbol, independent of where they come from."""

    @abstractmethod
    def get_latest_tick(self, symbol: str) -> Tick: ...

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]: ...
