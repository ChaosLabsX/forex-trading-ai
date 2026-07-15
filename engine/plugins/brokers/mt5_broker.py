from __future__ import annotations

from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from engine.config import Settings
from engine.core.interfaces.broker import BrokerAdapter
from engine.core.models import AccountState, ClosedTradePnl, Direction, Position, PositionStatus
from engine.sizing import SymbolLimits
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
    whatever terminal is already open and logged in instead.

    Either way the adapter binds to exactly ONE account and refuses to follow the
    terminal anywhere else - the bridge otherwise tracks the terminal silently,
    which is how 31 orders got refused as NO_MONEY on a funded account. See
    _bind_account() and docs/safety-rails.md."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._server_utc_offset_seconds: float = 0.0
        # The account this adapter is bound to. Set from MT5_LOGIN when one is
        # configured; otherwise captured from the terminal on the FIRST connect
        # and never rewritten - see _bind_account().
        self._bound_login: int | None = None

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

        info = mt5.account_info()
        if info is None:
            code, message = mt5.last_error()
            raise MT5ConnectionError(f"account_info() returned None right after initialize(): [{code}] {message}")

        terminal = mt5.terminal_info()
        terminal_path = getattr(terminal, "path", "unknown") if terminal else "unknown"
        # Always say which terminal and account we actually landed on. With two
        # terminals installed this is the difference between "the demo lab" and
        # "real money", and it was previously invisible.
        logger.info(
            "attached: account %s (%s) via %s", info.login, info.server, terminal_path
        )
        self._verify_server(info.server, terminal_path)
        self._bind_account(info.login)

        # MT5 timestamps are in the broker's server time, not UTC (confirmed:
        # ~3h offset on this account) - measured fresh on every (re)connect so
        # DST transitions don't need a code change.
        self._server_utc_offset_seconds = measure_server_utc_offset_seconds()

    def _verify_server(self, actual_server: str, terminal_path: str) -> None:
        """Refuse to run against the wrong broker server.

        This closes a real hole. `_bind_account()` only pins the LOGIN, and with
        MT5_LOGIN empty (attach-to-open-terminal mode) whatever account it first
        attaches to becomes "correct" by definition. Meanwhile an empty
        MT5_TERMINAL_PATH lets mt5.initialize() attach to whichever terminal
        Windows offers - fine with one terminal installed, dangerous the moment a
        second exists.

        So the demo engine, running TEST_MODE=true (real 0.01-lot orders), could
        attach to the LIVE terminal, bind to the live account as though intended,
        and trade real money while tagging every alert DEMO. Nothing would notice.

        MT5_SERVER is already configured and costs nothing to check, and the two
        servers differ (ICMarketsSC-Demo vs ICMarketsSC-MT5-3), so it catches
        exactly this. Pinning MT5_TERMINAL_PATH prevents the mix-up; this refuses
        to trade if it happens anyway."""
        expected = self._settings.mt5_server
        if not expected:
            logger.warning(
                "MT5_SERVER is not set - cannot verify which broker server this "
                "terminal is on. Set it, especially with more than one terminal installed."
            )
            return
        if actual_server != expected:
            raise MT5ConnectionError(
                f"attached to server '{actual_server}' but MT5_SERVER expects '{expected}' "
                f"- refusing to trade. Terminal: {terminal_path}. "
                f"Set MT5_TERMINAL_PATH to pin this engine to its own terminal."
            )

    def _bind_account(self, actual: int) -> None:
        """Decide - once - which account this adapter owns, and refuse to move.

        With MT5_LOGIN set, initialize(login=) should have logged us in, but it
        can report success without the login taking effect, so it is checked
        rather than trusted.

        With MT5_LOGIN empty (attach-to-open-terminal mode) there is nothing to
        check against, so the first account we attach to becomes the binding and
        any later change is treated as a fault. That is deliberate: without
        credentials the adapter cannot log back in, so drifting to another
        account is not something it can repair - only refuse.
        """
        expected = self._expected_login()
        if expected is not None and actual != expected:
            raise MT5ConnectionError(
                f"terminal is logged into account {actual}, expected {expected} - refusing to trade"
            )
        if self._bound_login is None:
            self._bound_login = actual
        elif actual != self._bound_login:
            raise MT5ConnectionError(
                f"terminal moved to account {actual}; this engine is bound to {self._bound_login} "
                f"- refusing to trade (set MT5_LOGIN/MT5_PASSWORD so it can log back in)"
            )

    def _expected_login(self) -> int | None:
        """The account MT5_LOGIN pins us to, or None in attach-to-open-terminal
        mode, where nothing was configured to hold the terminal to."""
        if not self._settings.mt5_login:
            return None
        return int(self._settings.mt5_login)

    def _to_utc(self, epoch_seconds: float) -> datetime:
        return server_epoch_to_utc(epoch_seconds, self._server_utc_offset_seconds)

    def disconnect(self) -> None:
        mt5.shutdown()

    def is_connected(self) -> bool:
        """Usable for trading OUR account right now - not merely "MT5.exe is running".

        Three different things break orders here, and the old check
        (`terminal_info() is not None`) could see none of them:

          * the terminal process is gone;
          * the terminal is up but has no trade-server link - terminal_info()
            still returns a struct in that state, so the object's existence
            proves nothing. `.connected` is the field that answers the question;
          * the terminal is logged into a DIFFERENT account. initialize(login=)
            runs once at connect; afterwards the IPC bridge silently follows the
            terminal wherever it is pointed.

        The last one cost two hours live on 2026-07-15: 31 orders refused as
        NO_MONEY while the intended account held $10M, because MT5 was not
        looking at that account - and every health check said "connected".

        Returning False is also the repair: the loop's reconnect path calls
        connect(), which re-runs initialize(login=) and logs back in.
        """
        info = mt5.terminal_info()
        if info is None or not info.connected:
            return False

        if self._bound_login is None:
            return True  # never connected yet - nothing to compare against
        account = mt5.account_info()
        return account is not None and account.login == self._bound_login

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

    def get_price_value_per_lot(self, symbol: str) -> float | None:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        tick_size = info.trade_tick_size or info.point
        if not tick_size:
            return None
        return float(info.trade_tick_value / tick_size)

    def get_symbol_limits(self, symbol: str) -> SymbolLimits | None:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        tick_size = info.trade_tick_size or info.point
        if not tick_size:
            return None
        return SymbolLimits(
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            value_per_price_per_lot=float(info.trade_tick_value / tick_size),
        )

    def calc_margin(self, symbol: str, direction: Direction, lots: float, price: float) -> float | None:
        margin = mt5.order_calc_margin(_ORDER_TYPE[direction], symbol, lots, price)
        return float(margin) if margin is not None else None

    def get_closed_position_pnl(self, position_id: str) -> float | None:
        breakdown = self.get_closed_position_breakdown(position_id)
        return breakdown.net if breakdown is not None else None

    def get_closed_position_breakdown(self, position_id: str) -> ClosedTradePnl | None:
        deals = mt5.history_deals_get(position=int(position_id))
        if not deals:
            return None
        # Require a closing deal so we don't report on a still-open position.
        if not any(d.entry == mt5.DEAL_ENTRY_OUT for d in deals):
            return None
        # Sum across ALL deals, not just the closing one: profit lands on the
        # exit deal, but commission is charged on entry AND exit, so a
        # closing-deal-only sum understates fees.
        return ClosedTradePnl(
            gross_profit=float(sum(d.profit for d in deals)),
            commission=float(sum(d.commission for d in deals)),
            swap=float(sum(d.swap for d in deals)),
        )

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
