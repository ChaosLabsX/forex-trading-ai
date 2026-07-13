from __future__ import annotations

from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.models import AccountState, Direction, Position, PositionStatus
from engine.plugins.brokers.mt5_time import measure_server_utc_offset_seconds, server_epoch_to_utc

_ORDER_TYPE = {
    Direction.LONG: mt5.ORDER_TYPE_BUY,
    Direction.SHORT: mt5.ORDER_TYPE_SELL,
}


class MT5ConnectionError(RuntimeError):
    pass


class MT5BrokerAdapter(BrokerAdapter):
    """Talks to a locally-running, logged-in MT5 terminal via the MetaTrader5
    IPC package. If MT5_LOGIN/PASSWORD/TERMINAL_PATH aren't set, attaches to
    whatever terminal is already open and logged in instead."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._server_utc_offset_seconds: float = 0.0

    def connect(self) -> None:
        kwargs: dict = {}
        if self._settings.mt5_terminal_path:
            kwargs["path"] = self._settings.mt5_terminal_path
        if self._settings.mt5_login:
            kwargs["login"] = int(self._settings.mt5_login)
            kwargs["password"] = self._settings.mt5_password
            kwargs["server"] = self._settings.mt5_server

        if not mt5.initialize(**kwargs):
            code, message = mt5.last_error()
            raise MT5ConnectionError(f"mt5.initialize() failed: [{code}] {message}")

        # MT5 timestamps are in the broker's server time, not UTC (confirmed:
        # ~3h offset on this account) - measured fresh on every (re)connect so
        # DST transitions don't need a code change.
        self._server_utc_offset_seconds = measure_server_utc_offset_seconds()

    def _to_utc(self, epoch_seconds: float) -> datetime:
        return server_epoch_to_utc(epoch_seconds, self._server_utc_offset_seconds)

    def disconnect(self) -> None:
        mt5.shutdown()

    def is_connected(self) -> bool:
        return mt5.terminal_info() is not None

    def get_account_state(self) -> AccountState:
        info = mt5.account_info()
        if info is None:
            code, message = mt5.last_error()
            raise MT5ConnectionError(f"account_info() failed: [{code}] {message}")
        positions = self.get_open_positions()
        daily_pnl, consecutive_losses = self._daily_stats()
        return AccountState(
            balance=info.balance,
            equity=info.equity,
            margin_used=info.margin,
            open_positions_count=len(positions),
            daily_pnl=daily_pnl,
            consecutive_stop_losses_today=consecutive_losses,
        )

    def _daily_stats(self) -> tuple[float, int]:
        """Real daily P&L and consecutive-losing-trade count from today's closed
        deals - the circuit breakers in RiskEngine depend on these being real,
        not placeholders. MT5 deal timestamps are in server time, and the exact
        timezone semantics of history_deals_get()'s query bounds aren't
        documented - rather than guess, query a generously wide window (+/-12h)
        and filter precisely using each deal's own corrected UTC time."""
        utc_today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        utc_now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(utc_today_start - timedelta(hours=12), utc_now + timedelta(hours=12))
        if not deals:
            return 0.0, 0

        closing_deals = sorted(
            (d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and self._to_utc(d.time) >= utc_today_start),
            key=lambda d: d.time,
        )
        daily_pnl = sum(d.profit + d.swap + d.commission for d in closing_deals)

        consecutive_losses = 0
        for deal in reversed(closing_deals):
            if deal.profit < 0:
                consecutive_losses += 1
            else:
                break
        return float(daily_pnl), consecutive_losses

    def get_open_positions(self) -> list[Position]:
        raw = mt5.positions_get()
        if raw is None:
            return []
        return [self._to_position(p) for p in raw]

    def place_order(
        self,
        symbol: str,
        direction: Direction,
        lot_size: float,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> Position:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5ConnectionError(f"symbol_info_tick({symbol}) returned None")
        price = tick.ask if direction == Direction.LONG else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": _ORDER_TYPE[direction],
            "price": price,
            "sl": stop_loss or 0.0,
            "tp": take_profit or 0.0,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code, message = mt5.last_error()
            raise MT5ConnectionError(
                f"order_send failed: retcode={getattr(result, 'retcode', None)} [{code}] {message}"
            )

        return Position(
            id=str(result.order),
            symbol=symbol,
            direction=direction,
            lot_size=lot_size,
            entry_price=result.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=PositionStatus.OPEN,
            opened_at=datetime.now(timezone.utc),
        )

    def modify_position(
        self,
        position_id: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Position:
        ticket = int(position_id)
        raw = mt5.positions_get(ticket=ticket)
        if not raw:
            raise MT5ConnectionError(f"position {position_id} not found")
        existing = raw[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": existing.symbol,
            "position": ticket,
            "sl": stop_loss if stop_loss is not None else existing.sl,
            "tp": take_profit if take_profit is not None else existing.tp,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code, message = mt5.last_error()
            raise MT5ConnectionError(f"modify failed: [{code}] {message}")
        return self._to_position(mt5.positions_get(ticket=ticket)[0])

    def close_position(self, position_id: str, volume: float | None = None) -> Position:
        ticket = int(position_id)
        raw = mt5.positions_get(ticket=ticket)
        if not raw:
            raise MT5ConnectionError(f"position {position_id} not found")
        existing = raw[0]

        direction = Direction.LONG if existing.type == mt5.ORDER_TYPE_BUY else Direction.SHORT
        close_direction = Direction.SHORT if direction == Direction.LONG else Direction.LONG
        tick = mt5.symbol_info_tick(existing.symbol)
        price = tick.bid if direction == Direction.LONG else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": existing.symbol,
            "volume": volume or existing.volume,
            "type": _ORDER_TYPE[close_direction],
            "position": ticket,
            "price": price,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code, message = mt5.last_error()
            raise MT5ConnectionError(f"close failed: [{code}] {message}")

        return Position(
            id=position_id,
            symbol=existing.symbol,
            direction=direction,
            lot_size=volume or existing.volume,
            entry_price=existing.price_open,
            stop_loss=existing.sl or None,
            take_profit=existing.tp or None,
            status=PositionStatus.CLOSED,
            opened_at=self._to_utc(existing.time),
            closed_at=datetime.now(timezone.utc),
            realized_pnl=result.profit if hasattr(result, "profit") else None,
        )

    def get_closed_position_pnl(self, position_id: str) -> float | None:
        deals = mt5.history_deals_get(position=int(position_id))
        if not deals:
            return None
        closing_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not closing_deals:
            return None
        return float(sum(d.profit + d.swap + d.commission for d in closing_deals))

    def _to_position(self, raw) -> Position:
        return Position(
            id=str(raw.ticket),
            symbol=raw.symbol,
            direction=Direction.LONG if raw.type == mt5.ORDER_TYPE_BUY else Direction.SHORT,
            lot_size=raw.volume,
            entry_price=raw.price_open,
            stop_loss=raw.sl or None,
            take_profit=raw.tp or None,
            status=PositionStatus.OPEN,
            opened_at=self._to_utc(raw.time),
        )
