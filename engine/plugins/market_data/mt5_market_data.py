from __future__ import annotations

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.market_data import MarketDataProvider, SymbolUnavailableError
from engine.core.models import Candle, Tick, Timeframe
from engine.plugins.brokers.mt5_time import measure_server_utc_offset_seconds, server_epoch_to_utc

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
        self._server_utc_offset_seconds: float | None = None

    def _offset(self) -> float:
        # Lazy + cached: this class has no connect() lifecycle hook of its
        # own (it rides on the broker adapter's mt5.initialize()), so the
        # offset is measured once on first use rather than eagerly.
        if self._server_utc_offset_seconds is None:
            self._server_utc_offset_seconds = measure_server_utc_offset_seconds()
        return self._server_utc_offset_seconds

    def get_latest_tick(self, symbol: str) -> Tick:
        raw = mt5.symbol_info_tick(symbol)
        if raw is None:
            code, message = mt5.last_error()
            raise MT5MarketDataError(f"symbol_info_tick({symbol}) failed: [{code}] {message}")
        return Tick(
            symbol=symbol,
            time=server_epoch_to_utc(raw.time, self._offset()),
            bid=raw.bid,
            ask=raw.ask,
        )

    def _retry_or_explain(self, symbol: str, timeframe: Timeframe, count: int, code, message):
        """Decide whether a failed history fetch is permanent, and fix it if not.

        copy_rates_from_pos returns None for three different situations and
        last_error() does not reliably tell them apart - the live engine saw
        [-1] "Terminal: Call failed" for a symbol that does not exist and
        [-10001] "IPC send failed" for one that momentarily stalled.
        symbol_info() separates them:

          * None while the terminal answers  -> the server has no such symbol.
          * present but not visible          -> real, just not in Market Watch.
            The terminal only serves history for selected symbols, so select it
            and retry. This is what lets a freshly installed terminal work
            without being set up by hand, and it is why the live engine's
            missing symbols were invisible until one turned out to be absent
            from the server entirely.
          * present and visible              -> transient; the caller logs it
            and retries next cycle, which is the existing behaviour.

        terminal_info() guards the obvious false positive: during a full IPC
        stall symbol_info() returns None for EVERY symbol, and declaring the
        whole universe permanently absent would be far worse than the noise
        this exists to stop.
        """
        info = mt5.symbol_info(symbol)
        if info is None:
            if mt5.terminal_info() is not None:
                raise SymbolUnavailableError(
                    f"{symbol} does not exist on this account's server "
                    f"(copy_rates_from_pos gave [{code}] {message})"
                )
        elif not info.visible:
            mt5.symbol_select(symbol, True)
            raw = mt5.copy_rates_from_pos(symbol, _TIMEFRAME_MAP[timeframe], 0, count)
            if raw is not None:
                return raw
            code, message = mt5.last_error()

        raise MT5MarketDataError(
            f"copy_rates_from_pos({symbol}, {timeframe}) failed: [{code}] {message}"
        )

    def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        mt5_timeframe = _TIMEFRAME_MAP[timeframe]
        raw = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
        if raw is None:
            # Read last_error() BEFORE any other MT5 call - it reports the most
            # recent one, so the diagnosis below would overwrite the reason.
            code, message = mt5.last_error()
            raw = self._retry_or_explain(symbol, timeframe, count, code, message)
        offset = self._offset()
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                time=server_epoch_to_utc(row["time"], offset),
                # cast explicitly - numpy scalar types (from the structured
                # array MT5 returns) aren't JSON-serializable as-is
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["tick_volume"]),
            )
            for row in raw
        ]
