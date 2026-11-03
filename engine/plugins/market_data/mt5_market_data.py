from __future__ import annotations

from datetime import datetime, timezone

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.market_data import MarketDataUnavailable, MarketDataProvider, SymbolUnavailableError
from engine.core.models import Candle, Tick, Timeframe
from engine.plugins.brokers.mt5_time import (
    ServerClock,
    clock_cache_path,
    follows_ny_close,
    ny_close_offset_seconds,
    server_epoch_to_utc,
    server_epoch_to_utc_ny_close,
)

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


class HistoryClockMismatch(MarketDataUnavailable):
    """The broker's measured offset is not what the New-York-close rule says it
    should be right now, so history cannot be relabelled with that rule. Raised
    rather than guessed: an hour's error is invisible in every downstream number."""


class MT5MarketDataProvider(MarketDataProvider):
    """Reads ticks/candles from the same terminal MT5BrokerAdapter connects to.
    Assumes mt5.initialize() has already been called (by the broker adapter)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Lazy: this class has no connect() hook of its own (it rides on the
        # broker adapter's mt5.initialize()), so the clock measures on first
        # use. ServerClock owns the caching, refreshing and refusal - see
        # mt5_time.py for why measuring this wrong is so quiet.
        self._clock = ServerClock(cache_path=clock_cache_path(settings.account_key))

    def _offset(self) -> float:
        return self._clock.offset()

    def get_latest_tick(self, symbol: str) -> Tick:
        raw = mt5.symbol_info_tick(symbol)
        if raw is None:
            code, message = mt5.last_error()
            raise MT5MarketDataError(f"symbol_info_tick({symbol}) failed: [{code}] {message}")
        return Tick(
            symbol=symbol,
            time=self._clock.to_utc(raw.time),
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

    def _rates(self, symbol: str, timeframe: Timeframe, count: int):
        raw = mt5.copy_rates_from_pos(symbol, _TIMEFRAME_MAP[timeframe], 0, count)
        if raw is None:
            # Read last_error() BEFORE any other MT5 call - it reports the most
            # recent one, so the diagnosis below would overwrite the reason.
            code, message = mt5.last_error()
            raw = self._retry_or_explain(symbol, timeframe, count, code, message)
        return raw

    @staticmethod
    def _candle(symbol: str, timeframe: Timeframe, row, time) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            time=time,
            # cast explicitly - numpy scalar types (from the structured
            # array MT5 returns) aren't JSON-serializable as-is
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["tick_volume"]),
        )

    def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        raw = self._rates(symbol, timeframe, count)
        # Once for the whole batch: every row shares the offset, and a
        # re-measure mid-batch could split one window across two clocks. Right
        # for the engine's recent windows; see get_history for long ones.
        offset = self._offset()
        return [self._candle(symbol, timeframe, row, server_epoch_to_utc(row["time"], offset)) for row in raw]

    def get_history(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        """Every bar stamped with the offset in force when it formed (the
        New-York-close rule, mt5_time.py) - after checking that the rule agrees
        with the offset measured right now. If it does not, this broker is not
        on that convention and nothing is relabelled."""
        measured = self._offset()
        now = datetime.now(timezone.utc)
        if not follows_ny_close(measured, now):
            raise HistoryClockMismatch(
                f"broker offset measured {measured / 3600:+.2f}h, but the New-York-close rule says "
                f"{ny_close_offset_seconds(now) / 3600:+.2f}h for now - refusing to relabel history with it"
            )
        raw = self._rates(symbol, timeframe, count)
        return [self._candle(symbol, timeframe, row, server_epoch_to_utc_ny_close(row["time"])) for row in raw]
