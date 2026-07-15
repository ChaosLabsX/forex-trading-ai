from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import Candle, ClosedTradePnl, NotificationEvent, Position, Timeframe
from engine.evaluator import ReadinessEvaluator
from engine.gating import StrategyGate
from engine.registry import EngineComposition
from engine.reporting import (
    build_daily_summary,
    engine_event,
    format_readiness_change,
    parse_daily_time,
    stop_moved,
    trade_closed,
    trade_opened,
)
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.loop")

CONTEXT_TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
# H4 needs to cover EMATrendStrategy's REGIME_SLOW_EMA (200) + margin, or every
# evaluation silently fails at the "insufficient history" check before any
# real logic runs - caught via backtest producing suspiciously zero signals.
CANDLE_COUNT = {Timeframe.H1: 300, Timeframe.H4: 250, Timeframe.D1: 90}

POLL_INTERVAL_SECONDS = 2
HEARTBEAT_INTERVAL_SECONDS = 60
CANDLE_REFRESH_INTERVAL_SECONDS = 60
# Trailing/breakeven stops react to intra-minute price, so manage open
# positions far more often than the 60s candle cycle (but not every 2s tick -
# a modify only matters when price has meaningfully advanced).
MANAGE_INTERVAL_SECONDS = 5
RECONNECT_BACKOFF_SECONDS = (5, 10, 30, 60)
# The daily digest only fires inside this window after its scheduled time, so a
# restart later in the day can't resend it.
DAILY_SUMMARY_WINDOW_MINUTES = 30


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
    """Connection management, data persistence, strategy evaluation, and (as of
    Phase 3) risk-checked order execution with trade lifecycle tracking."""

    def __init__(
        self, engine: EngineComposition, supabase: SupabaseClient, settings: Settings | None = None
    ) -> None:
        self._engine = engine
        self._supabase = supabase
        self._settings = settings or Settings()
        self._account_key = self._settings.account_key
        self._gate = StrategyGate(supabase, self._settings)
        self._evaluator = ReadinessEvaluator(supabase, self._settings)
        self._connected = False
        self._backoff_index = 0
        self._last_heartbeat = 0.0
        self._last_candle_refresh = 0.0
        self._last_manage = 0.0
        self._last_evaluation = 0.0
        self._last_summary_date: date | None = None
        # (strategy_name, symbol) -> timestamp of the last *closed* entry-timeframe
        # bar we evaluated, so we log each closed bar's outcome exactly once
        self._last_evaluated_bar: dict[tuple[str, str], datetime] = {}
        # strategy -> last logged block reason, so a permanent block (e.g. live
        # sizing missing) is reported once rather than every single cycle
        self._logged_blocks: dict[str, str] = {}
        # broker ticket -> owning strategy, refreshed each cycle from `trades`
        self._ticket_owner: dict[str, str] = {}
        self._paused = False
        # Instruments are whatever the configured strategies actually ask for -
        # never a second hardcoded list to fall out of sync with them. Widening a
        # strategy's coverage is then a plugin change, nothing else.
        self._instruments: tuple[str, ...] = tuple(
            dict.fromkeys(sym for s in engine.strategies for sym in s.instruments)
        )

    # ------------------------------------------------------------- identity

    def _account(self):
        return self._gate.account()

    def _account_label(self) -> str:
        account = self._account()
        return account.account_type.upper() if account else self._account_key

    def _is_lab(self) -> bool:
        """The demo account is the laboratory: it owns readiness verdicts."""
        account = self._account()
        return account is not None and account.account_type == "demo"

    def run_forever(self) -> None:
        known = [s.name for s in self._engine.strategies]
        self._gate.sync_strategies(known)
        account = self._account()
        if account is None:
            logger.error(
                "account '%s' is not registered - nothing will trade until it is", self._account_key
            )
        else:
            logger.info("engine account: %s (%s)", account.key, account.account_type)
        gate = self._gate.gate(known, force=True)
        if gate.account_block:
            logger.warning("ACCOUNT BLOCKED: %s", gate.account_block)

        _notify_all(
            self._engine,
            "startup",
            engine_event(
                "🚀",
                "ENGINE STARTED",
                f"{self._account_label()}  ·  {len(known)} strategies  ·  {len(self._instruments)} symbols",
                gate.account_block or "",
            ),
        )
        try:
            while True:
                self._tick()
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("shutdown requested")
            _notify_all(self._engine, "shutdown", engine_event("⏹", "ENGINE STOPPED", self._account_label()))
        finally:
            if self._engine.broker is not None:
                try:
                    self._engine.broker.disconnect()
                except Exception:
                    logger.exception("error during broker disconnect")

    def _tick(self) -> None:
        self._ensure_connected()
        if self._connected:
            self._process_commands()
        now = time.monotonic()
        if self._connected and now - self._last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            self._send_heartbeat()
            self._last_heartbeat = now
        if self._connected and now - self._last_candle_refresh >= CANDLE_REFRESH_INTERVAL_SECONDS:
            self._refresh_market_data_and_evaluate()
            self._last_candle_refresh = now
        if self._connected and now - self._last_manage >= MANAGE_INTERVAL_SECONDS:
            self._manage_open_positions()
            self._last_manage = now
        # Evaluation and the digest read only Supabase, so they keep working
        # (and keep reporting) even while the broker is down.
        if now - self._last_evaluation >= self._settings.evaluation_interval_minutes * 60:
            self._run_evaluation()
            self._last_evaluation = now
        self._maybe_send_daily_summary()

    # ---------------------------------------------------- strategy lifecycle

    def _run_evaluation(self) -> None:
        if not self._is_lab():
            return  # only the lab judges readiness
        try:
            self._evaluator.run(on_change=self._on_readiness_change)
        except Exception:
            logger.exception("readiness evaluation failed")

    def _on_readiness_change(self, strategy: dict, previous, evaluation) -> None:
        _notify_all(
            self._engine, "readiness_changed", format_readiness_change(strategy, previous, evaluation)
        )
        self._gate.gate([s.name for s in self._engine.strategies], force=True)

    def _maybe_send_daily_summary(self) -> None:
        if not self._settings.daily_summary_enabled:
            return
        target = parse_daily_time(self._settings.daily_summary_utc_time)
        if target is None:
            return
        now = datetime.now(timezone.utc)
        if self._last_summary_date == now.date():
            return
        scheduled = datetime.combine(now.date(), target)
        # Only fire inside a short window after the target: a restart hours
        # later must not resend the digest.
        if not (scheduled <= now < scheduled + timedelta(minutes=DAILY_SUMMARY_WINDOW_MINUTES)):
            return
        self._last_summary_date = now.date()
        try:
            gate = self._gate.gate([s.name for s in self._engine.strategies])
            _notify_all(
                self._engine,
                "daily_summary",
                build_daily_summary(self._supabase, gate.account_block, now),
            )
            logger.info("daily summary sent")
        except Exception:
            logger.exception("failed to build/send daily summary")

    def _ensure_connected(self) -> None:
        broker = self._engine.broker
        if broker is None:
            return

        if broker.is_connected():
            if not self._connected:
                self._connected = True
                self._backoff_index = 0
                logger.info("broker connected")
                _notify_all(self._engine, "broker_connected", engine_event("🔌", "BROKER CONNECTED", self._account_label()))
            return

        if self._connected:
            self._connected = False
            logger.warning("broker disconnected")
            _notify_all(
                self._engine,
                "broker_disconnected",
                engine_event("⚠️", "BROKER DISCONNECTED", self._account_label(), "reconnecting"),
            )

        try:
            broker.connect()
            self._connected = True
            self._backoff_index = 0
            logger.info("broker (re)connected")
            _notify_all(self._engine, "broker_connected", engine_event("🔌", "BROKER RECONNECTED", self._account_label()))
        except Exception as exc:
            wait = RECONNECT_BACKOFF_SECONDS[min(self._backoff_index, len(RECONNECT_BACKOFF_SECONDS) - 1)]
            logger.error("reconnect failed, retrying in %ss: %s", wait, exc)
            self._backoff_index += 1
            time.sleep(wait)

    def _send_heartbeat(self) -> None:
        # status carries the pause state so the dashboard can show PAUSED vs
        # LIVE - the engine keeps heartbeating and monitoring while paused, it
        # just won't open new trades (see _evaluate_strategies).
        status = "paused" if self._paused else "running"
        try:
            self._supabase.insert(
                "engine_heartbeats",
                [
                    {
                        "status": status,
                        "broker_connected": self._connected,
                        "detail": None,
                        "account_key": self._account_key,
                    }
                ],
            )
            logger.info("heartbeat sent (%s)", status)
        except Exception:
            logger.exception("failed to send heartbeat to Supabase")

    def _immediate_heartbeat(self) -> None:
        # Push the current state right away (e.g. just after a pause/resume) so
        # the dashboard reflects it within its poll interval instead of waiting
        # up to a full HEARTBEAT_INTERVAL_SECONDS for the next scheduled one.
        self._send_heartbeat()
        self._last_heartbeat = time.monotonic()

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
                self._reconcile_closed_trades(open_positions)
                self._refresh_ownership()
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

        for symbol in self._instruments:
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

    def _refresh_ownership(self) -> None:
        """Map broker ticket -> owning strategy, from our own trades table.

        MT5 has no idea which strategy opened a position, so without this every
        strategy sees every other strategy's trades. Two things went wrong as a
        result, both fatal to a research lab:

          * a strategy was BLOCKED from a symbol another strategy happened to
            reach first - and a signal that never fires is never recorded, so
            each strategy's record was biased by its neighbours' luck;
          * strategies opened opposite sides of one symbol on the same bar (a
            real GBPJPY long AND short, seconds apart) because the shared
            position snapshot predated both trades.

        Ownership makes each strategy an independent experiment that shares only
        a price feed. Positions we have no record of (opened by hand, or
        predating this) belong to nobody and stay hidden from every strategy."""
        try:
            rows = self._supabase.select(
                "trades", {"status": "eq.OPEN", "account_key": f"eq.{self._account_key}"}
            )
        except Exception:
            logger.exception("failed to map positions to strategies - skipping this cycle")
            return
        self._ticket_owner = {r["mt5_ticket"]: r["strategy_name"] for r in rows}

    def _positions_of(self, strategy_name: str, open_positions: list) -> list:
        return [p for p in open_positions if self._ticket_owner.get(p.id) == strategy_name]

    def _process_commands(self) -> None:
        try:
            # Only this account's commands - with two engines running, each must
            # ignore the other's pause/close instructions.
            pending = self._supabase.select(
                "commands",
                {
                    "status": "eq.pending",
                    "account_key": f"eq.{self._account_key}",
                    "order": "created_at.asc",
                },
            )
        except Exception:
            logger.exception("failed to fetch pending commands")
            return

        for row in pending:
            command_id = row["id"]
            command_type = row["command_type"]
            try:
                if command_type == "pause":
                    self._paused = True
                    logger.info("PAUSED via dashboard command")
                    _notify_all(self._engine, "paused", engine_event("⏸", "PAUSED", self._account_label(), "no new trades"))
                    self._immediate_heartbeat()
                elif command_type == "resume":
                    self._paused = False
                    logger.info("RESUMED via dashboard command")
                    _notify_all(self._engine, "resumed", engine_event("▶️", "RESUMED", self._account_label()))
                    self._immediate_heartbeat()
                elif command_type == "emergency_close_all":
                    self._emergency_close_all()
                else:
                    logger.warning("unknown command type: %s", command_type)
            except Exception:
                logger.exception("failed to process command %s (%s)", command_id, command_type)
                continue

            try:
                self._supabase.update(
                    "commands",
                    {"id": f"eq.{command_id}"},
                    {"status": "processed", "processed_at": datetime.now(timezone.utc).isoformat()},
                )
            except Exception:
                logger.exception("failed to mark command %s processed", command_id)

    def _emergency_close_all(self) -> None:
        broker = self._engine.broker
        if broker is None:
            return
        positions = broker.get_open_positions()
        logger.warning("EMERGENCY CLOSE ALL: closing %d open position(s)", len(positions))
        _notify_all(
            self._engine, "emergency_close", f"Emergency close-all triggered: closing {len(positions)} position(s)."
        )
        for position in positions:
            try:
                broker.close_position(position.id)
            except Exception:
                logger.exception("failed to close position %s during emergency close-all", position.id)

    def _manage_open_positions(self) -> None:
        """Per-cycle breakeven/trailing-stop management. Purely protective (it
        only ever tightens a stop toward profit), so it runs even while paused -
        pausing stops opening new trades, not guarding open ones."""
        broker = self._engine.broker
        execution_engine = self._engine.execution_engine
        market_data = self._engine.market_data
        if broker is None or execution_engine is None or market_data is None:
            return

        try:
            positions = broker.get_open_positions()
        except Exception:
            logger.exception("failed to fetch open positions for stop management")
            return

        for position in positions:
            try:
                tick = market_data.get_latest_tick(position.symbol)
            except Exception:
                logger.exception("failed to fetch tick for %s during management", position.symbol)
                continue
            try:
                updated = execution_engine.manage_open_position(position, tick, broker)
            except Exception:
                logger.exception("failed managing position %s", position.id)
                continue
            if updated is not None:
                self._on_stop_moved(updated)

    def _on_stop_moved(self, position: Position) -> None:
        try:
            self._supabase.update(
                "trades", {"mt5_ticket": f"eq.{position.id}"}, {"stop_loss": position.stop_loss}
            )
        except Exception:
            logger.exception("failed to sync moved stop for trade %s", position.id)
        _notify_all(
            self._engine,
            "stop_moved",
            stop_moved(position, self._account_label()),
        )

    def _evaluate_strategies(
        self,
        symbol: str,
        candles_by_timeframe: dict[Timeframe, list[Candle]],
        account_state,
        open_positions: list,
        upcoming_news: tuple,
    ) -> None:
        if self._paused:
            return
        gate = self._gate.gate([s.name for s in self._engine.strategies])
        for strategy in self._engine.strategies:
            if symbol not in strategy.instruments:
                continue
            if strategy.name not in gate.eligible:
                # No fallback: if the registry doesn't clear it, it doesn't trade.
                self._log_block_once(strategy.name, gate.blocked.get(strategy.name, "not eligible"))
                continue
            self._logged_blocks.pop(strategy.name, None)
            if not all(tf in candles_by_timeframe and candles_by_timeframe[tf] for tf in strategy.required_timeframes):
                continue

            entry_timeframe = strategy.required_timeframes[0]
            latest_closed_bar_time = candles_by_timeframe[entry_timeframe][-1].time
            dedupe_key = (strategy.name, symbol)
            if self._last_evaluated_bar.get(dedupe_key) == latest_closed_bar_time:
                continue  # already evaluated this closed bar - avoid duplicate log rows

            # Only this strategy's own positions. Each strategy is an
            # independent experiment that happens to share a price feed; showing
            # it a neighbour's trades is what let them block each other and hedge
            # the same symbol on one bar.
            own_positions = self._positions_of(strategy.name, open_positions)

            try:
                context = StrategyContext(
                    symbol=symbol,
                    candles_by_timeframe=candles_by_timeframe,
                    account_state=account_state,
                    open_positions=own_positions,
                    upcoming_news=upcoming_news,
                )
                evaluation = strategy.evaluate(context)
            except Exception:
                logger.exception("strategy %s failed evaluating %s", strategy.name, symbol)
                continue

            self._last_evaluated_bar[dedupe_key] = latest_closed_bar_time

            risk_approved = None
            risk_reason = None
            if evaluation.signal is not None:
                logger.info("SIGNAL fired: %s %s %s", strategy.name, symbol, evaluation.signal.direction.value)
                # No Telegram for a fired signal: it is immediately followed by
                # either an OPEN alert or a rejection, so announcing it as well
                # just doubles the traffic to say the same thing.
                # Own positions again, so max_concurrent_trades caps each
                # strategy rather than being a shared pool they race for -
                # whoever lost that race had a signal silently dropped.
                risk_approved, risk_reason = self._route_through_risk_engine(
                    strategy.name, evaluation.signal, account_state, own_positions
                )
            else:
                logger.info("no signal: %s %s - %s", strategy.name, symbol, evaluation.reason)

            signal_id = self._log_signal(strategy.name, symbol, evaluation, risk_approved, risk_reason)

            if evaluation.signal is not None and signal_id is not None:
                self._review_with_ai(signal_id, evaluation.signal, context)

    def _review_with_ai(self, signal_id: int, signal, context: StrategyContext) -> None:
        """Shadow mode: logs Claude's opinion for later comparison, never
        gates execution - RiskEngine's decision already ran before this."""
        ai_provider = self._engine.ai_provider
        if ai_provider is None:
            return

        try:
            verdict = ai_provider.review_signal(signal, context)
        except Exception:
            logger.exception("AI review failed for signal %s", signal_id)
            return

        logger.info(
            "AI review: signal=%s approved=%s confidence=%.2f", signal_id, verdict.approved, verdict.confidence
        )
        try:
            self._supabase.insert(
                "ai_reviews",
                [
                    {
                        "signal_id": signal_id,
                        # from the provider, never a second hardcoded copy - the
                        # stored label must be the model that actually ran
                        "model": ai_provider.model_name,
                        "approved": verdict.approved,
                        "confidence": verdict.confidence,
                        "rationale": verdict.rationale,
                    }
                ],
            )
        except Exception:
            logger.exception("failed to persist AI review for signal %s", signal_id)

    def _route_through_risk_engine(self, strategy_name: str, signal, account_state, open_positions) -> tuple:
        risk_engine = self._engine.risk_engine
        broker = self._engine.broker
        if risk_engine is None:
            return None, "no risk engine configured - signal not traded"
        if broker is None:
            return None, "no broker configured - signal not traded"

        try:
            decision = risk_engine.validate_signal(
                signal,
                account_state,
                open_positions,
                broker,
                risk_pct=self._gate.risk_pct_for(strategy_name),
            )
        except Exception:
            logger.exception("risk engine failed validating %s %s", strategy_name, signal.symbol)
            return False, "risk engine raised an exception - see logs"

        if not decision.approved:
            logger.info("signal rejected by risk engine: %s %s - %s", strategy_name, signal.symbol, decision.reason)
            _notify_all(self._engine, "signal_rejected", f"{strategy_name} {signal.symbol}: {decision.reason}")
        elif decision.order is not None:
            self._open_trade(strategy_name, decision.order)

        return decision.approved, decision.reason

    def _open_trade(self, strategy_name: str, approved_order) -> None:
        broker = self._engine.broker
        execution_engine = self._engine.execution_engine
        if broker is None or execution_engine is None:
            logger.warning("cannot execute %s: broker or execution_engine not configured", strategy_name)
            return

        # Snapshot before executing - a client-side error (e.g. a timeout)
        # doesn't guarantee the broker didn't actually fill the order. Found
        # live: an order that raised MT5ConnectionError(timeout) had in fact
        # filled - without this check it becomes a real position with no
        # trades row, invisible to reconciliation forever.
        positions_before = {p.id for p in broker.get_open_positions()}

        try:
            position = execution_engine.execute(approved_order, broker)
        except Exception:
            logger.exception("order execution failed for %s %s", strategy_name, approved_order.signal.symbol)
            position = self._find_orphaned_position(broker, approved_order, positions_before)
            if position is None:
                _notify_all(
                    self._engine,
                    "execution_failed",
                    f"{strategy_name} {approved_order.signal.symbol}: order placement failed, see logs",
                )
                return
            logger.warning(
                "order for %s %s actually filled despite a client-side error - recovered as ticket %s",
                strategy_name, approved_order.signal.symbol, position.id,
            )
            _notify_all(
                self._engine,
                "trade_recovered",
                f"{strategy_name} {approved_order.signal.symbol}: order filled despite a client-side "
                f"error - recovered as ticket {position.id}.",
            )

        self._persist_opened_trade(strategy_name, position)

    @staticmethod
    def _find_orphaned_position(broker, approved_order, positions_before: set) -> Position | None:
        signal = approved_order.signal
        for position in broker.get_open_positions():
            if position.id in positions_before:
                continue
            if (
                position.symbol == signal.symbol
                and position.direction == signal.direction
                and abs(position.lot_size - approved_order.lot_size) < 1e-9
            ):
                return position
        return None

    def _risk_amount(self, position) -> float | None:
        """Account-currency amount this trade puts at risk if its initial stop
        is hit. Recorded at open because trailing later rewrites stop_loss - and
        without it, R-multiples (and therefore every readiness verdict) become
        uncomputable for this trade forever."""
        broker = self._engine.broker
        if broker is None or position.stop_loss is None:
            return None
        try:
            value_per_price = broker.get_price_value_per_lot(position.symbol)
        except Exception:
            logger.exception("failed to read tick value for %s", position.symbol)
            return None
        if not value_per_price:
            return None
        distance = abs(position.entry_price - position.stop_loss)
        return distance * value_per_price * position.lot_size

    def _persist_opened_trade(self, strategy_name: str, position) -> None:
        risk_amount = self._risk_amount(position)
        if risk_amount is None:
            logger.warning(
                "no risk_amount for trade %s - it will be excluded from R-based evaluation",
                position.id,
            )
        try:
            self._supabase.insert(
                "trades",
                [
                    {
                        "mt5_ticket": position.id,
                        "strategy_name": strategy_name,
                        "symbol": position.symbol,
                        "direction": position.direction.value,
                        "lot_size": position.lot_size,
                        "entry_price": position.entry_price,
                        "stop_loss": position.stop_loss,
                        "initial_stop_loss": position.stop_loss,
                        "risk_amount": risk_amount,
                        "take_profit": position.take_profit,
                        "status": "OPEN",
                        "opened_at": position.opened_at.isoformat(),
                        "account_key": self._account_key,
                    }
                ],
            )
        except Exception:
            logger.exception("failed to persist opened trade %s", position.id)

        logger.info(
            "TRADE OPENED: %s %s %s %s lot @ %s",
            strategy_name, position.symbol, position.direction.value, position.lot_size, position.entry_price,
        )
        _notify_all(
            self._engine,
            "trade_opened",
            trade_opened(position, strategy_name, self._account_label(), risk_amount),
        )

    def _reconcile_closed_trades(self, open_positions: list) -> None:
        broker = self._engine.broker
        if broker is None:
            return

        open_tickets = {p.id for p in open_positions}
        try:
            # MUST filter by account. Without it every engine reconciles every
            # OTHER account's trades: it looks up a ticket that was never in its
            # terminal, concludes the position closed, and writes CLOSED with a
            # null P&L. Two engines then race to destroy each other's data - and
            # since the evaluator skips trades with no P&L, the lab silently
            # collects nothing at all while looking healthy.
            open_trade_rows = self._supabase.select(
                "trades", {"status": "eq.OPEN", "account_key": f"eq.{self._account_key}"}
            )
        except Exception:
            logger.exception("failed to fetch open trades from Supabase for reconciliation")
            return

        for row in open_trade_rows:
            ticket = row["mt5_ticket"]
            if ticket in open_tickets:
                continue  # still open

            try:
                breakdown = broker.get_closed_position_breakdown(ticket)
            except Exception:
                logger.exception("failed to fetch closed P&L for ticket %s", ticket)
                breakdown = None

            net = breakdown.net if breakdown is not None else None
            try:
                self._supabase.update(
                    "trades",
                    {"mt5_ticket": f"eq.{ticket}"},
                    {
                        "status": "CLOSED",
                        "realized_pnl": net,
                        "closed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                logger.exception("failed to persist closed trade %s", ticket)
                continue

            net_text = f"{net:+.2f}" if net is not None else "unknown"
            logger.info(
                "TRADE CLOSED: %s %s ticket=%s net=%s", row["strategy_name"], row["symbol"], ticket, net_text
            )
            _notify_all(
                self._engine,
                "trade_closed",
                trade_closed(
                    row["symbol"],
                    row.get("direction"),
                    breakdown,
                    strategy=row.get("strategy_name", ""),
                    account=self._account_label(),
                ),
            )

    def _log_block_once(self, strategy_name: str, reason: str) -> None:
        if self._logged_blocks.get(strategy_name) == reason:
            return
        self._logged_blocks[strategy_name] = reason
        logger.info("strategy %s not trading on %s: %s", strategy_name, self._account_key, reason)

    def _log_signal(
        self, strategy_name: str, symbol: str, evaluation, risk_approved=None, risk_reason=None
    ) -> int | None:
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
            "risk_approved": risk_approved,
            "risk_reason": risk_reason,
            "account_key": self._account_key,
        }
        try:
            inserted = self._supabase.insert("signals", [row], returning=True)
            return inserted[0]["id"] if inserted else None
        except Exception:
            logger.exception("failed to log signal for %s %s", strategy_name, symbol)
            return None
