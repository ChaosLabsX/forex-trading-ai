from __future__ import annotations

import logging
import time
from datetime import datetime

from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import Candle, NotificationEvent, Timeframe
from engine.registry import EngineComposition
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.loop")

INSTRUMENTS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
CONTEXT_TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
# H4 needs to cover EMATrendStrategy's REGIME_SLOW_EMA (200) + margin, or every
# evaluation silently fails at the "insufficient history" check before any
# real logic runs - caught via backtest producing suspiciously zero signals.
CANDLE_COUNT = {Timeframe.H1: 300, Timeframe.H4: 250, Timeframe.D1: 90}

POLL_INTERVAL_SECONDS = 2
HEARTBEAT_INTERVAL_SECONDS = 60
CANDLE_REFRESH_INTERVAL_SECONDS = 60
RECONNECT_BACKOFF_SECONDS = (5, 10, 30, 60)


def _closed_only(candles: list[Candle]) -> list[Candle]:
    # copy_rates_from_pos(..., 0, ...) includes the current, still-forming bar
    # at the end - indicators must never evaluate against an incomplete bar,
    # or a crossover reading would flip-flop as price moves within the hour.
    return candles[:-1] if len(candles) > 1 else candles


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
        # (strategy_name, symbol) -> timestamp of the last *closed* entry-timeframe
        # bar we evaluated, so we log each closed bar's outcome exactly once
        self._last_evaluated_bar: dict[tuple[str, str], datetime] = {}

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
            self._refresh_market_data_and_evaluate()
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

    def _refresh_market_data_and_evaluate(self) -> None:
        market_data = self._engine.market_data
        if market_data is None:
            return

        broker = self._engine.broker
        account_state = None
        open_positions: list = []
        if broker is not None:
            try:
                account_state = broker.get_account_state()
                open_positions = broker.get_open_positions()
            except Exception:
                logger.exception("failed to fetch account state/open positions")

        upcoming_news: tuple = ()
        if self._engine.news_provider is not None:
            try:
                upcoming_news = tuple(
                    self._engine.news_provider.get_upcoming_events(window_minutes=120)
                )
            except Exception:
                logger.exception("failed to fetch upcoming news events")

        for symbol in INSTRUMENTS:
            candles_by_timeframe: dict[Timeframe, list[Candle]] = {}
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
                    candles_by_timeframe[timeframe] = _closed_only(candles)
                except Exception:
                    logger.exception("failed to refresh candles for %s %s", symbol, timeframe.value)

            if account_state is not None:
                self._evaluate_strategies(
                    symbol, candles_by_timeframe, account_state, open_positions, upcoming_news
                )

    def _evaluate_strategies(
        self,
        symbol: str,
        candles_by_timeframe: dict[Timeframe, list[Candle]],
        account_state,
        open_positions: list,
        upcoming_news: tuple,
    ) -> None:
        for strategy in self._engine.strategies:
            if symbol not in strategy.instruments:
                continue
            if not all(tf in candles_by_timeframe and candles_by_timeframe[tf] for tf in strategy.required_timeframes):
                continue

            entry_timeframe = strategy.required_timeframes[0]
            latest_closed_bar_time = candles_by_timeframe[entry_timeframe][-1].time
            dedupe_key = (strategy.name, symbol)
            if self._last_evaluated_bar.get(dedupe_key) == latest_closed_bar_time:
                continue  # already evaluated this closed bar - avoid duplicate log rows

            try:
                context = StrategyContext(
                    symbol=symbol,
                    candles_by_timeframe=candles_by_timeframe,
                    account_state=account_state,
                    open_positions=open_positions,
                    upcoming_news=upcoming_news,
                )
                evaluation = strategy.evaluate(context)
            except Exception:
                logger.exception("strategy %s failed evaluating %s", strategy.name, symbol)
                continue

            self._last_evaluated_bar[dedupe_key] = latest_closed_bar_time
            self._log_signal(strategy.name, symbol, evaluation)

            if evaluation.signal is not None:
                logger.info("SIGNAL fired: %s %s %s", strategy.name, symbol, evaluation.signal.direction.value)
                _notify_all(
                    self._engine,
                    "signal_fired",
                    f"{strategy.name} {symbol} {evaluation.signal.direction.value}: {evaluation.reason}",
                )
            else:
                logger.info("no signal: %s %s - %s", strategy.name, symbol, evaluation.reason)

    def _log_signal(self, strategy_name: str, symbol: str, evaluation) -> None:
        signal = evaluation.signal
        row = {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "fired": signal is not None,
            "direction": signal.direction.value if signal else None,
            "timeframe": signal.timeframe.value if signal else None,
            "entry_price": signal.entry_price if signal else None,
            "stop_loss": signal.stop_loss if signal else None,
            "take_profit": signal.take_profit if signal else None,
            "reason": evaluation.reason,
            "metadata": signal.metadata if signal else None,
        }
        try:
            self._supabase.insert("signals", [row])
        except Exception:
            logger.exception("failed to log signal for %s %s", strategy_name, symbol)
