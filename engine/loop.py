from __future__ import annotations

import logging
import time

from engine.core.models import NotificationEvent, Timeframe
from engine.registry import EngineComposition
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.loop")

INSTRUMENTS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
CONTEXT_TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
CANDLE_COUNT = {Timeframe.H1: 300, Timeframe.H4: 150, Timeframe.D1: 90}

POLL_INTERVAL_SECONDS = 2
HEARTBEAT_INTERVAL_SECONDS = 60
CANDLE_REFRESH_INTERVAL_SECONDS = 60
RECONNECT_BACKOFF_SECONDS = (5, 10, 30, 60)


def _notify_all(engine: EngineComposition, event_type: str, message: str) -> None:
    for notifier in engine.notifications:
        try:
            notifier.notify(NotificationEvent(event_type=event_type, message=message))
        except Exception:
            logger.exception("notification provider failed")


def _candle_row(candle) -> dict:
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.value,
        "time": candle.time.isoformat(),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


class EngineLoop:
    """Phase 1 scope: connection management + data persistence only. No
    strategy evaluation, risk checks, or order execution yet (Phases 2-3)."""

    def __init__(self, engine: EngineComposition, supabase: SupabaseClient) -> None:
        self._engine = engine
        self._supabase = supabase
        self._connected = False
        self._backoff_index = 0
        self._last_heartbeat = 0.0
        self._last_candle_refresh = 0.0

    def run_forever(self) -> None:
        _notify_all(self._engine, "startup", "Engine loop starting.")
        try:
            while True:
                self._tick()
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("shutdown requested")
            _notify_all(self._engine, "shutdown", "Engine loop stopped (keyboard interrupt).")
        finally:
            if self._engine.broker is not None:
                try:
                    self._engine.broker.disconnect()
                except Exception:
                    logger.exception("error during broker disconnect")

    def _tick(self) -> None:
        self._ensure_connected()
        now = time.monotonic()
        if self._connected and now - self._last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            self._send_heartbeat()
            self._last_heartbeat = now
        if self._connected and now - self._last_candle_refresh >= CANDLE_REFRESH_INTERVAL_SECONDS:
            self._refresh_candles()
            self._last_candle_refresh = now

    def _ensure_connected(self) -> None:
        broker = self._engine.broker
        if broker is None:
            return

        if broker.is_connected():
            if not self._connected:
                self._connected = True
                self._backoff_index = 0
                logger.info("broker connected")
                _notify_all(self._engine, "broker_connected", "MT5 broker connected.")
            return

        if self._connected:
            self._connected = False
            logger.warning("broker disconnected")
            _notify_all(
                self._engine, "broker_disconnected", "MT5 broker disconnected - attempting to reconnect."
            )

        try:
            broker.connect()
            self._connected = True
            self._backoff_index = 0
            logger.info("broker (re)connected")
            _notify_all(self._engine, "broker_connected", "MT5 broker (re)connected.")
        except Exception as exc:
            wait = RECONNECT_BACKOFF_SECONDS[min(self._backoff_index, len(RECONNECT_BACKOFF_SECONDS) - 1)]
            logger.error("reconnect failed, retrying in %ss: %s", wait, exc)
            self._backoff_index += 1
            time.sleep(wait)

    def _send_heartbeat(self) -> None:
        try:
            self._supabase.insert(
                "engine_heartbeats",
                [{"status": "running", "broker_connected": self._connected, "detail": None}],
            )
            logger.info("heartbeat sent")
        except Exception:
            logger.exception("failed to send heartbeat to Supabase")

    def _refresh_candles(self) -> None:
        market_data = self._engine.market_data
        if market_data is None:
            return
        for symbol in INSTRUMENTS:
            for timeframe in CONTEXT_TIMEFRAMES:
                try:
                    candles = market_data.get_candles(symbol, timeframe, CANDLE_COUNT[timeframe])
                    if not candles:
                        continue
                    self._supabase.upsert(
                        "candles",
                        [_candle_row(c) for c in candles],
                        on_conflict="symbol,timeframe,time",
                    )
                    logger.info("refreshed %s %s: %d candles", symbol, timeframe.value, len(candles))
                except Exception:
                    logger.exception("failed to refresh candles for %s %s", symbol, timeframe.value)
