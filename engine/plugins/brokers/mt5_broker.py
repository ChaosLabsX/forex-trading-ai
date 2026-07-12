from __future__ import annotations

from datetime import datetime, timezone

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.models import AccountState, Direction, Position, PositionStatus

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
        return AccountState(
            balance=info.balance,
            equity=info.equity,
            margin_used=info.margin,
            open_positions_count=len(positions),
            daily_pnl=0.0,
            consecutive_stop_losses_today=0,
        )

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
            opened_at=datetime.fromtimestamp(existing.time, tz=timezone.utc),
            closed_at=datetime.now(timezone.utc),
            realized_pnl=result.profit if hasattr(result, "profit") else None,
        )

    @staticmethod
    def _to_position(raw) -> Position:
        return Position(
            id=str(raw.ticket),
            symbol=raw.symbol,
            direction=Direction.LONG if raw.type == mt5.ORDER_TYPE_BUY else Direction.SHORT,
            lot_size=raw.volume,
            entry_price=raw.price_open,
            stop_loss=raw.sl or None,
            take_profit=raw.tp or None,
            status=PositionStatus.OPEN,
            opened_at=datetime.fromtimestamp(raw.time, tz=timezone.utc),
        )
