from __future__ import annotations

from datetime import datetime, timezone

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.market_data import MarketDataProvider
from engine.core.models import Candle, Tick, Timeframe

_TIMEFRAME_MAP = {
    Timeframe.M1: mt5.TIMEFRAME_M1,
    Timeframe.M5: mt5.TIMEFRAME_M5,
    Timeframe.M15: mt5.TIMEFRAME_M15,
    Timeframe.M30: mt5.TIMEFRAME_M30,
    Timeframe.H1: mt5.TIMEFRAME_H1,
    Timeframe.H4: mt5.TIMEFRAME_H4,
    Timeframe.D1: mt5.TIMEFRAME_D1,
}


class MT5MarketDataError(RuntimeError):
    pass


class MT5MarketDataProvider(MarketDataProvider):
    """Reads ticks/candles from the same terminal MT5BrokerAdapter connects to.
    Assumes mt5.initialize() has already been called (by the broker adapter)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_latest_tick(self, symbol: str) -> Tick:
        raw = mt5.symbol_info_tick(symbol)
        if raw is None:
            code, message = mt5.last_error()
            raise MT5MarketDataError(f"symbol_info_tick({symbol}) failed: [{code}] {message}")
        return Tick(
            symbol=symbol,
            time=datetime.fromtimestamp(raw.time, tz=timezone.utc),
            bid=raw.bid,
            ask=raw.ask,
        )

    def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        mt5_timeframe = _TIMEFRAME_MAP[timeframe]
        raw = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
        if raw is None:
            code, message = mt5.last_error()
            raise MT5MarketDataError(
                f"copy_rates_from_pos({symbol}, {timeframe}) failed: [{code}] {message}"
            )
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                time=datetime.fromtimestamp(row["time"], tz=timezone.utc),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["tick_volume"],
            )
            for row in raw
        ]
