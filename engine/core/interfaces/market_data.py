from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.models import Candle, Tick, Timeframe


class MarketDataUnavailable(RuntimeError):
    """The provider cannot serve ANY symbol right now.

    Distinct from SymbolUnavailableError, which is one symbol's problem: this
    means the cycle is pointless, so a caller should stop rather than fail once
    per symbol and bury the reason under N identical tracebacks.
    """


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

    def get_history(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        """Like get_candles, but every bar is stamped with the UTC offset in force
        when IT formed - for windows long enough to cross a daylight-saving
        switch (backtests, trade autopsies). get_candles' single current offset
        is right for the engine's recent windows and an hour wrong across a
        switch. Concrete: a provider without the distinction serves get_candles."""
        return self.get_candles(symbol, timeframe, count)
