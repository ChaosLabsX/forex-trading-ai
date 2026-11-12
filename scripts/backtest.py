"""Backtest + statistical evaluation for ANY registered strategy.

    python scripts/backtest.py ema_trend_v1

This is the fast screening filter in front of the demo lab. The lab needs ~100
live trades to reach a verdict, which at a typical trade rate is measured in
years - so learning an idea is worthless by waiting for live data is the slowest
possible way to learn it. This replays the same idea over years of real history
in about two minutes. Screen here first; only promote survivors to the lab.

Walks historical H1/H4 candles bar-by-bar through the exact same
StrategyPlugin.evaluate() the live engine uses (same window sizes as
engine/loop.py's CANDLE_COUNT), then simulates each fired signal forward to see
whether its stop-loss or take-profit would have been hit first - now with
transaction costs, realistic fills, and proper statistics.

Open trades are managed the way the engine manages them: the stop moves to
entry at +1R (and trails past +2R), driven by the engine's own
DefaultExecutionEngine with the same Settings. Until 2026-10-12 the backtest
held every stop fixed, so it tested a strategy that wasn't the one trading - on
demo, 14% of london_breakout_v1's trades ended at a stop moved to entry, an
outcome the backtest could not produce. Both models are printed: managed (the
headline, what really trades) and fixed (comparable with every result recorded
in docs/research-log.md before that date).

What makes this more than the old sanity check:
  - Transaction costs modelled from live MT5 symbol info (spread) plus an
    assumed commission, deducted from every trade in R terms. Ignoring costs is
    the single most common way a backtest lies - a strategy with a tiny edge
    per trade can flip from "profitable" to "bleeds out on costs" once spread
    and commission are charged.
  - Entries fill at the *next* bar's open, not the signal bar's close (no
    "enter at the price that just triggered me" lookahead).
  - Full metrics: expectancy (R/trade), profit factor, win rate, avg win/loss
    R, max drawdown (R), longest losing streak, and a bootstrap 95% confidence
    interval on expectancy - the actual test of "is this edge distinguishable
    from zero, or just noise in this sample?"
  - A chronological first-half / second-half split, so a result that only
    worked in one regime doesn't hide inside a flattering total.

It is still ONE historical path from ONE broker/account, with intrabar order
assumed conservatively (see caveats printed at the end). It does not optimise
parameters and is not walk-forward out-of-sample. Treat a positive result as
"worth paper-trading forward," never as a guarantee.

"""

from __future__ import annotations

import statistics
import sys
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyPlugin
from engine.core.models import AccountState, Direction, Position, PositionStatus, Tick, Timeframe
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.brokers.mt5_time import ny_close_offset_seconds
from engine.plugins.execution.default_execution_engine import DefaultExecutionEngine
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider
from engine.registry import PLUGIN_REGISTRY, load_plugin
from engine.stats import bootstrap_expectancy_ci, longest_losing_streak, max_drawdown_r

# Windows must match engine/loop.py CANDLE_COUNT, or the backtest feeds a
# strategy a different amount of history than production does and measures
# something that will never actually trade.
WINDOW = {Timeframe.H1: 300, Timeframe.H4: 250, Timeframe.D1: 90}
# Hours per bar, used to request the same span of history across timeframes.
TF_HOURS = {
    Timeframe.M1: 1 / 60,
    Timeframe.M5: 5 / 60,
    Timeframe.M15: 0.25,
    Timeframe.M30: 0.5,
    Timeframe.H1: 1.0,
    Timeframe.H4: 4.0,
    Timeframe.D1: 24.0,
}
ENTRY_HISTORY_BARS = 20_000  # ask big; the broker returns what it has
# Give up on a trade that never resolves within ~8 trading days of H1 bars. The
# engine has no such limit, so a strategy built to hold for weeks declares its
# own (`backtest_max_hold_bars`) rather than have its winners cut off here.
MAX_HOLD_BARS = 200

# MT5's SYMBOL_SWAP_MODE_* values: how a symbol's overnight financing is quoted.
SWAP_DISABLED, SWAP_POINTS, SWAP_BASE_CURRENCY, SWAP_MARGIN_CURRENCY, SWAP_DEPOSIT_CURRENCY = 0, 1, 2, 3, 4
SWAP_PCT_OF_CURRENT_PRICE, SWAP_PCT_OF_OPEN_PRICE = 5, 6

# IC Markets "Raw Spread" charges commission separately from the (near-zero)
# spread: ~$3.50 per lot per side, i.e. ~$7 round-turn per 1.0 lot. Override
# here if your account's schedule differs. Expressed per 1.0 lot; the R-cost it
# produces is lot-size-independent (see _cost_in_r), so this stays valid no
# matter what lot the live risk engine actually sizes.
COMMISSION_PER_LOT_ROUNDTURN = 7.0
# ...and only on these. Measured from 2,060 of the demo account's own deals
# (2026-11-13): $3.50 a lot a side on every FX pair and metal, $0.00 on every
# index, energy and crypto deal. Charging $7 a lot everywhere made a small-
# contract index cost most of its own risk. Matched against symbol_info().path.
COMMISSIONED_PATHS = ("Forex\\", "Commodities\\Metal")


def commission_for(path: str) -> float:
    """Round-turn commission per 1.0 lot for a symbol, from its broker group."""
    return COMMISSION_PER_LOT_ROUNDTURN if path.startswith(COMMISSIONED_PATHS) else 0.0

PLACEHOLDER_ACCOUNT = AccountState(
    balance=10_000.0,
    equity=10_000.0,
    margin_used=0.0,
    open_positions_count=0,
    daily_pnl=0.0,
    consecutive_stop_losses_today=0,
)


@dataclass
class SymbolCosts:
    """Per-trade transaction cost for a symbol, resolved once from MT5."""

    spread_price: float  # current spread expressed in price units
    value_per_price_per_lot: float  # account-currency value of a 1.0 price move, 1.0 lot
    min_stop_price: float  # broker's own minimum stop distance, in price units
    point: float
    available: bool  # False if symbol_info was missing - costs then default to spread only
    # Overnight financing per calendar night, signed as the broker states it
    # (negative = the position pays). Either a price amount per unit, or a
    # yearly percentage of the price - brokers quote FX the first way and
    # indices the second. See swap_terms().
    swap_long_price: float = 0.0
    swap_short_price: float = 0.0
    swap_long_pct: float = 0.0
    swap_short_pct: float = 0.0
    swap_known: bool = True  # False: quoted in a way this model cannot price
    commission_per_lot: float = COMMISSION_PER_LOT_ROUNDTURN  # round turn; see commission_for


@dataclass(frozen=True)
class SimResult:
    result: str  # "win" | "loss" | "moved_stop" | "timeout"
    gross_r: float
    bars_held: int  # bars walked, counting the one the trade ended in


@dataclass
class TradeOutcome:
    symbol: str
    direction: Direction
    entry_time: object
    entry_price: float
    stop_loss: float
    take_profit: float
    result: str  # "win" | "loss" | "moved_stop" | "timeout"
    gross_r: float  # R before costs
    net_r: float  # R after spread + commission
    cost_r: float  # what costs took, so the model stays auditable
    risk_price: float
    # The same trade with the stop held fixed - the model used before
    # 2026-10-12, kept so the two can be compared on identical signals.
    fixed_result: str = ""
    fixed_gross_r: float = 0.0
    # Commission alone as a share of the risk (spread excluded) - the quantity
    # the demo lab's fee records measure, so the 2026-11-03 cost hypothesis is
    # tested on the same footing it was found on.
    commission_r: float = 0.0
    # Overnight financing over the nights the trade was held, in R, signed
    # (negative = paid). Already inside net_r.
    swap_r: float = 0.0
    fixed_swap_r: float = 0.0

    def as_fixed(self) -> "TradeOutcome":
        return replace(self, result=self.fixed_result, gross_r=self.fixed_gross_r,
                       swap_r=self.fixed_swap_r,
                       net_r=self.fixed_gross_r - self.cost_r + self.fixed_swap_r)


def swap_terms(mode: int, swap_long: float, swap_short: float, point: float,
               value_per_price: float, contract_size: float = 0.0,
               quoted_in_profit_currency: bool = False) -> tuple[float, float, float, float, bool]:
    """(long price/night, short price/night, long %/year, short %/year, known)
    from the broker's swap quote. A mode this cannot price returns known=False
    with zeros - reported, never guessed."""
    if mode == SWAP_DISABLED:
        return 0.0, 0.0, 0.0, 0.0, True
    if mode == SWAP_POINTS:
        return swap_long * point, swap_short * point, 0.0, 0.0, True
    if mode in (SWAP_BASE_CURRENCY, SWAP_MARGIN_CURRENCY) and quoted_in_profit_currency and contract_size > 0:
        # Money per 1.0 lot per night, in the currency the price itself is in
        # (how this broker quotes stock indices): per unit, that IS a price.
        return swap_long / contract_size, swap_short / contract_size, 0.0, 0.0, True
    if mode == SWAP_DEPOSIT_CURRENCY and value_per_price > 0:
        # money per 1.0 lot per night -> the price move worth that much
        return swap_long / value_per_price, swap_short / value_per_price, 0.0, 0.0, True
    if mode in (SWAP_PCT_OF_CURRENT_PRICE, SWAP_PCT_OF_OPEN_PRICE):
        return 0.0, 0.0, swap_long, swap_short, True
    return 0.0, 0.0, 0.0, 0.0, False


def nights_held(entry_utc: datetime, exit_utc: datetime) -> int:
    """Broker midnights between entry and exit - the rollovers a position paid
    financing at. Calendar days on purpose: the broker charges three nights on
    one weekday to cover the weekend, so the total is one a calendar day."""
    def server_date(utc: datetime):
        return (utc + timedelta(seconds=ny_close_offset_seconds(utc))).date()
    return max((server_date(exit_utc) - server_date(entry_utc)).days, 0)


def swap_in_r(costs: SymbolCosts, direction: Direction, entry_price: float,
              risk_price: float, nights: int) -> float:
    """Financing over `nights`, as a fraction of 1R; negative = paid."""
    if risk_price <= 0 or nights <= 0:
        return 0.0
    is_long = direction == Direction.LONG
    per_night = costs.swap_long_price if is_long else costs.swap_short_price
    pct = costs.swap_long_pct if is_long else costs.swap_short_pct
    per_night += entry_price * pct / 100.0 / 360.0
    return nights * per_night / risk_price


def resolve_costs(symbol: str) -> SymbolCosts:
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"  WARNING: symbol_info({symbol}) is None - costs will be ignored for it")
        return SymbolCosts(0.0, 0.0, 0.0, 0.0, False)
    if not info.select:
        # Dynamic fields are only trustworthy once the symbol is in Market Watch.
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol) or info
    spread_price = info.spread * info.point  # info.spread is a point count (snapshot)
    tick_size = info.trade_tick_size or info.point
    value_per_price = (info.trade_tick_value / tick_size) if tick_size else 0.0
    swap_currency = {SWAP_BASE_CURRENCY: info.currency_base, SWAP_MARGIN_CURRENCY: info.currency_margin}
    long_price, short_price, long_pct, short_pct, swap_known = swap_terms(
        info.swap_mode, info.swap_long, info.swap_short, info.point, value_per_price,
        contract_size=info.trade_contract_size,
        quoted_in_profit_currency=swap_currency.get(info.swap_mode) == info.currency_profit,
    )
    if not swap_known:
        print(f"  WARNING: {symbol} quotes overnight financing in a mode this model cannot "
              f"price (swap_mode {info.swap_mode}) - financing is NOT charged for it")
    return SymbolCosts(
        spread_price=spread_price,
        value_per_price_per_lot=value_per_price,
        min_stop_price=info.trade_stops_level * info.point,
        point=info.point,
        available=True,
        swap_long_price=long_price,
        swap_short_price=short_price,
        swap_long_pct=long_pct,
        swap_short_pct=short_pct,
        swap_known=swap_known,
        commission_per_lot=commission_for(info.path),
    )


def min_tradeable_stop(costs: SymbolCosts) -> float:
    """Smallest stop distance that could exist as a real order.

    This is the fix for a silent disaster: cost_in_r is 7/(risk x value), a
    hyperbola, so as the stop shrinks toward zero the modelled cost explodes
    toward infinity. During dead holiday sessions ATR collapses to a fraction of
    a pip, and an ATR-multiple stop collapses with it - producing "trades"
    costing tens of R that swamp every honest trade in the average.

    Those trades are fiction: MT5 rejects a stop inside trade_stops_level, and
    no one trades a stop narrower than the spread. Skipping them is FAITHFUL to
    what could actually have been executed, not data cleaning to flatter the
    result."""
    floor = max(
        costs.min_stop_price,        # the broker's own rule
        costs.spread_price * 2.0,    # a stop inside the spread is not a trade
        costs.point * 10.0,          # ~1 pip on a 5-digit FX pair
    )
    return floor


def commission_in_r(costs: SymbolCosts, risk_price: float) -> float:
    """The round-trip commission alone, as a fraction of 1R (lot-size free)."""
    if risk_price <= 0 or not costs.available or costs.value_per_price_per_lot <= 0:
        return 0.0
    return costs.commission_per_lot / (risk_price * costs.value_per_price_per_lot)


def cost_in_r(costs: SymbolCosts, risk_price: float) -> float:
    """Round-trip cost of a trade, expressed as a fraction of 1R.

    spread is already in price units, so spread_R = spread / risk. commission is
    a fixed currency amount; dividing by (risk_price * value_per_price_per_lot)
    converts it to R and the lot size cancels out, so this holds for any lot."""
    if risk_price <= 0:
        return 0.0
    return costs.spread_price / risk_price + commission_in_r(costs, risk_price)


class _PaperBroker:
    """Just enough of BrokerAdapter for DefaultExecutionEngine to move a stop.
    The backtest never places an order; a "modify" here only updates the copy
    of the position the simulation is walking forward."""

    current: Position

    def modify_position(self, position_id, stop_loss=None, take_profit=None):
        return self.current if stop_loss is None else replace(self.current, stop_loss=stop_loss)


class StopManager:
    """The engine's own stop management, driven bar by bar.

    Uses DefaultExecutionEngine.manage_open_position - not a copy of its rules -
    so the backtest moves a stop exactly when, and to exactly where, the engine
    would: breakeven at Settings.breakeven_at_r, trailing past trail_start_r,
    never by less than MIN_STEP_R, never loosened."""

    def __init__(self, settings: Settings) -> None:
        self._engine = DefaultExecutionEngine(settings)
        self._broker = _PaperBroker()
        self._next_id = 0

    def open(self, direction: Direction, entry: float, stop: float, target: float) -> Position:
        self._next_id += 1  # fresh id: the engine caches each position's initial risk by id
        return Position(f"bt-{self._next_id}", "", direction, 0.0, entry, stop, target,
                        PositionStatus.OPEN, None)

    def stop_after(self, position: Position, price: float) -> float:
        """Where the engine would put the stop having seen `price`."""
        self._broker.current = position
        tick = Tick(position.symbol, None, price, price)
        updated = self._engine.manage_open_position(position, tick, self._broker)
        return position.stop_loss if updated is None else updated.stop_loss


def simulate_outcome(
    direction: Direction,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    future_bars,
    manager: StopManager | None = None,
) -> tuple[str, float]:
    """Gross R (before costs) walking H1 bars forward from the entry.

    Each bar is read as open -> worst price -> best price -> close. That order is
    the conservative one: if a single bar touches both stop and target, the stop
    fills first. Timeouts mark to the last bar's close rather than being
    discarded - a trade left open for 8 days isn't a free scratch, it carries
    whatever P&L it had.

    With a manager the stop is managed as the engine manages it: having seen the
    bar's best price, the engine may move the stop (to entry at +1R). The move
    counts from that point on - for the rest of the bar (if it closes beyond the
    new stop, the stop was hit on the way there) and for every later bar. Without
    one, the stop stays where the strategy put it, as before 2026-10-12."""
    sim = simulate_trade(direction, entry_price, stop_loss, take_profit, future_bars, manager)
    return sim.result, sim.gross_r


def simulate_trade(
    direction: Direction,
    entry_price: float,
    stop_loss: float,
    take_profit: float | None,
    future_bars,
    manager: StopManager | None = None,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> SimResult:
    """simulate_outcome, also saying how many bars the trade lasted - which is
    what lets the caller keep one position per symbol and charge financing for
    the nights held. `take_profit=None` is a trade with no target: it ends at
    its stop (wherever the engine has moved it to) or at the hold limit."""
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return SimResult("loss", -1.0, 0)
    is_long = direction == Direction.LONG
    position = manager.open(direction, entry_price, stop_loss, take_profit) if manager else None
    stop = stop_loss

    def stopped_out(bars: int) -> SimResult:
        if stop == stop_loss:
            return SimResult("loss", -1.0, bars)
        signed = (stop - entry_price) if is_long else (entry_price - stop)
        return SimResult("moved_stop", signed / risk, bars)

    last_close = entry_price
    held = 0
    for held, bar in enumerate(future_bars[:max_hold_bars], start=1):
        last_close = bar.close
        worst, best = (bar.low, bar.high) if is_long else (bar.high, bar.low)
        if (worst <= stop) if is_long else (worst >= stop):
            return stopped_out(held)
        if take_profit is not None and ((best >= take_profit) if is_long else (best <= take_profit)):
            reward = abs(take_profit - entry_price)
            return SimResult("win", reward / risk, held)
        if manager is not None:
            new_stop = manager.stop_after(position, best)
            if new_stop != stop:
                stop = new_stop
                position = replace(position, stop_loss=stop)
                if (bar.close <= stop) if is_long else (bar.close >= stop):
                    return stopped_out(held)
    # never resolved: mark to market at the last close we saw
    signed = (last_close - entry_price) if is_long else (entry_price - last_close)
    return SimResult("timeout", signed / risk, held)


def closed_context(bars: list, times: list, as_of: datetime, entry_tf: Timeframe,
                   tf: Timeframe, window: int) -> list:
    """The last `window` bars of a slower timeframe that had CLOSED when the
    entry bar that opened at `as_of` closed - which is when the strategy runs.

    A bar is stamped with its OPEN time. The slice used to take every slower
    bar that had opened by `as_of`, which includes the one still forming: an H4
    bar opened at 08:00 was handed to an evaluation made at 10:00, carrying its
    high, low and close up to 12:00. So every two-timeframe strategy was tested
    with a filter that could see up to one slower bar into the future (3 hours
    for H1+H4, 20 for H4+D1) - which the engine, reading only closed bars,
    never can. Found 2026-11-13. A slower bar opened at t is closed at the
    evaluation only if t + its length <= as_of + the entry bar's length."""
    cutoff = as_of + timedelta(hours=TF_HOURS[entry_tf]) - timedelta(hours=TF_HOURS[tf])
    end = bisect_right(times, cutoff)
    return bars[max(0, end - window) : end]


def run_backtest_for_symbol(
    strategy: StrategyPlugin, md: MT5MarketDataProvider, symbol: str, manager: StopManager
) -> list[TradeOutcome]:
    # Timeframes come from the STRATEGY, never hardcoded here. The previous
    # version fetched H1+H4 regardless of what was asked for, so a strategy
    # wanting D1 (range_fade_h4_v1) hit "insufficient history" on every bar and
    # reported zero trades - which reads as "this idea never triggers" rather
    # than "the tool cannot run this idea". A silently empty result is the worst
    # kind of wrong.
    entry_tf = strategy.required_timeframes[0]
    context_tfs = tuple(strategy.required_timeframes[1:])
    entry_window = WINDOW[entry_tf]

    # get_history, not get_candles: years of bars cross many daylight-saving
    # switches, and one offset for all of them put london_breakout's session an
    # hour off for two thirds of every year (found 2026-11-03).
    entry_all = md.get_history(symbol, entry_tf, ENTRY_HISTORY_BARS)[:-1]  # drop forming bar
    if len(entry_all) <= entry_window + 2:
        return []
    # Said out loud, because the terminal serves whatever history it has
    # downloaded so far: a symbol it has only a year of looks exactly like a
    # symbol that rarely trades.
    print(f"  ({symbol}: {len(entry_all)} {entry_tf.value} bars, from {entry_all[0].time:%Y-%m-%d})")

    # Ask each context timeframe for the SAME span of history the entry bars
    # cover, so a slower regime filter isn't starved on long runs.
    span_hours = len(entry_all) * TF_HOURS[entry_tf]
    context_bars: dict = {}
    context_times: dict = {}
    for tf in context_tfs:
        needed = int(span_hours / TF_HOURS[tf]) + WINDOW[tf] + 2
        bars = md.get_history(symbol, tf, needed)[:-1]
        context_bars[tf] = bars
        context_times[tf] = [c.time for c in bars]

    costs = resolve_costs(symbol)
    max_hold = getattr(strategy, "backtest_max_hold_bars", MAX_HOLD_BARS)

    outcomes: list[TradeOutcome] = []
    last_signal_index = -(10**9)
    floor = min_tradeable_stop(costs)
    untradeable = 0
    # ONE POSITION PER SYMBOL, as the engine trades it. Every strategy declines
    # a symbol it already holds, but the backtest used to show it an empty book
    # on every bar - so a signal that repeats while the first trade is still
    # open was counted again, a trade the engine would never have placed. The
    # open trade is now handed to the strategy until the bar it ends on.
    open_position: Position | None = None
    open_until = -1

    # stop at len-2: a signal on bar i needs bar i+1 to exist to fill the entry
    for i in range(entry_window, len(entry_all) - 2):
        window = entry_all[i - entry_window : i + 1]
        as_of = window[-1].time

        candles: dict = {entry_tf: window}
        starved = False
        for tf in context_tfs:
            # Only bars that had already CLOSED when this one did - see
            # closed_context for the look-ahead this replaced.
            sliced = closed_context(context_bars[tf], context_times[tf], as_of, entry_tf, tf, WINDOW[tf])
            if len(sliced) < WINDOW[tf]:
                starved = True
                break
            candles[tf] = sliced
        if starved:
            continue

        context = StrategyContext(
            symbol=symbol,
            candles_by_timeframe=candles,
            account_state=PLACEHOLDER_ACCOUNT,
            open_positions=[open_position] if open_position is not None and i < open_until else [],
            upcoming_news=(),
        )
        evaluation = strategy.evaluate(context)
        if evaluation.signal is None:
            continue
        if i - last_signal_index < 2:
            continue  # same closed bar re-triggering via a shifted window edge case
        last_signal_index = i

        signal = evaluation.signal
        # Realistic fill: enter at the NEXT bar's open, not the price that just
        # triggered the signal. Re-derive risk from the actual fill so R is
        # honest, keeping the strategy's own stop/target levels.
        entry_fill = entry_all[i + 1].open
        risk_price = abs(entry_fill - signal.stop_loss)
        # A stop this tight could never have been placed (broker stops-level,
        # or narrower than the spread). Counting it would let 1/risk blow the
        # cost model up and swamp every real trade.
        if risk_price < floor:
            untradeable += 1
            continue

        future = entry_all[i + 2 :]
        managed = simulate_trade(
            signal.direction, entry_fill, signal.stop_loss, signal.take_profit, future, manager, max_hold
        )
        fixed = simulate_trade(
            signal.direction, entry_fill, signal.stop_loss, signal.take_profit, future, None, max_hold
        )
        entry_bar = entry_all[i + 1]
        open_position = Position("bt-open", symbol, signal.direction, 0.0, entry_fill, signal.stop_loss,
                                 signal.take_profit, PositionStatus.OPEN, entry_bar.time)
        open_until = i + 1 + managed.bars_held  # the bar the managed trade ends on

        def financing(sim: SimResult) -> float:
            exit_bar = future[sim.bars_held - 1] if sim.bars_held else entry_bar
            return swap_in_r(costs, signal.direction, entry_fill, risk_price,
                             nights_held(entry_bar.time, exit_bar.time))

        cost_r = cost_in_r(costs, risk_price)
        commission_r = commission_in_r(costs, risk_price)
        swap_r = financing(managed)
        outcomes.append(
            TradeOutcome(
                symbol=symbol,
                direction=signal.direction,
                entry_time=as_of,
                entry_price=entry_fill,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                result=managed.result,
                gross_r=managed.gross_r,
                net_r=managed.gross_r - cost_r + swap_r,
                cost_r=cost_r,
                risk_price=risk_price,
                fixed_result=fixed.result,
                fixed_gross_r=fixed.gross_r,
                commission_r=commission_r,
                swap_r=swap_r,
                fixed_swap_r=financing(fixed),
            )
        )
    if untradeable:
        print(
            f"  ({symbol}: skipped {untradeable} signals whose stop was below the "
            f"tradeable floor {floor:.5f} - they could not have been orders)"
        )
    return outcomes


# --- statistics -------------------------------------------------------------


def summarize(label: str, outcomes: list[TradeOutcome]) -> None:
    n = len(outcomes)
    if n == 0:
        print(f"{label}: no trades")
        return
    wins = [o for o in outcomes if o.result == "win"]
    losses = [o for o in outcomes if o.result == "loss"]
    moved = [o for o in outcomes if o.result == "moved_stop"]
    timeouts = [o for o in outcomes if o.result == "timeout"]
    resolved = len(wins) + len(losses) + len(moved)
    win_rate = (len(wins) / resolved * 100) if resolved else 0.0

    net_rs = [o.net_r for o in outcomes]
    gross_total = sum(o.gross_r for o in outcomes)
    net_total = sum(net_rs)
    expectancy = net_total / n
    avg_win = statistics.mean(o.net_r for o in wins) if wins else 0.0
    avg_loss = statistics.mean(o.net_r for o in losses) if losses else 0.0

    gains = sum(r for r in net_rs if r > 0)
    pains = -sum(r for r in net_rs if r < 0)
    profit_factor = (gains / pains) if pains > 0 else float("inf")

    lo, hi = bootstrap_expectancy_ci(net_rs)
    edge = "POSITIVE" if lo > 0 else ("negative" if hi < 0 else "not distinguishable from zero")

    # GROSS is measured, never inferred. It answers a different question to net:
    # "does this predict price at all?" - independent of what the broker charges.
    # A significant gross edge with a losing net says the idea works and the
    # tolls exceed it, which is a completely different problem to a dead idea.
    # I once asserted this CI from arithmetic instead of computing it; a claim
    # that a real edge exists has to be measured.
    gross_rs = [o.gross_r for o in outcomes]
    glo, ghi = bootstrap_expectancy_ci(gross_rs)
    gross_edge = (
        "POSITIVE" if glo > 0 else ("negative" if ghi < 0 else "not distinguishable from zero")
    )

    print(f"{label}:")
    moved_text = f" / {len(moved)} at moved stop" if moved else ""
    print(f"  trades           {n}  ({len(wins)}W / {len(losses)}L{moved_text} / {len(timeouts)} timeout)")
    print(f"  win rate         {win_rate:.1f}%  (target hits, of resolved)")
    # A strategy with no target never "wins" by the line above; this is the
    # share of trades that made money, however they ended.
    print(f"  net positive     {100 * sum(1 for r in net_rs if r > 0) / n:.1f}% of trades")
    print(f"  total R          gross {gross_total:+.2f}   net {net_total:+.2f}   (costs cut {gross_total - net_total:.2f}R)")
    swap_total = sum(o.swap_r for o in outcomes)
    if swap_total:
        print(f"  financing        {swap_total:+.2f}R in total, {swap_total / n:+.3f}R a trade  (overnight swap, inside net)")
    print(f"  expectancy       {expectancy:+.3f} R/trade")
    print(f"  avg win / loss   {avg_win:+.2f}R / {avg_loss:+.2f}R")
    print(f"  profit factor    {profit_factor:.2f}")
    # Costs shown as a distribution, not just a total: an average hides the
    # 1/risk tail that wrecked the first run, and a median wildly out of line
    # with ~0.05R means the model is lying again.
    cost_rs = sorted(o.cost_r for o in outcomes)
    if cost_rs:
        med = cost_rs[len(cost_rs) // 2]
        p95 = cost_rs[min(int(0.95 * len(cost_rs)), len(cost_rs) - 1)]
        print(f"  cost per trade   median {med:.3f}R  p95 {p95:.3f}R  max {cost_rs[-1]:.3f}R")
    print(f"  max drawdown     {max_drawdown_r(net_rs):.2f}R")
    print(f"  longest losing   {longest_losing_streak(net_rs)} in a row")
    print(f"  expectancy 95%CI [{lo:+.3f}, {hi:+.3f}] R/trade  -> edge {edge}")
    print(
        f"  GROSS expectancy {gross_total / n:+.3f} R/trade  95%CI [{glo:+.3f}, {ghi:+.3f}]"
        f"  -> signal {gross_edge}"
    )
    if glo > 0 and lo <= 0:
        print("     ^ the idea predicts price, but costs exceed what it predicts")
    print()


# --- pre-registered checks (docs/research-log.md, 2026-11-03) -----------------
#
# Two filters suggested by slicing the demo lab's london breakout trades, tested
# ONCE here on history they did not come from. The criteria were written down
# before the first run and are not to be adjusted after it: no other hour, no
# other threshold. Judged on the managed-stop outcomes (how the engine trades).

PREREG_FIRST_HOUR = 7  # UTC hour the breakout bar opens - the London open
PREREG_COMMISSION_CAP = 0.08  # commission as a share of the risk


def subset_stats(outcomes: list[TradeOutcome]) -> dict | None:
    """Net expectancy, its bootstrap CI and the chronological halves of a subset
    (outcomes must be in time order), and whether it meets the pre-registered
    bar: CI entirely above zero AND both halves positive."""
    if not outcomes:
        return None
    net = [o.net_r for o in outcomes]
    lo, hi = bootstrap_expectancy_ci(net)
    mid = len(net) // 2
    first = statistics.mean(net[:mid]) if mid else float("nan")
    second = statistics.mean(net[mid:])
    return {
        "n": len(net),
        "mean": statistics.mean(net),
        "lo": lo,
        "hi": hi,
        "first": first,
        "second": second,
        "wins": sum(1 for o in outcomes if o.result == "win") / len(net),
        "passed": lo > 0 and first > 0 and second > 0,
    }


def _subset_line(label: str, outcomes: list[TradeOutcome], judged: bool = False) -> None:
    st = subset_stats(outcomes)
    if st is None:
        print(f"    {label:32s}     0 trades")
        return
    verdict = ("   PASS" if st["passed"] else "   fail") if judged else ""
    print(
        f"    {label:32s} {st['n']:5d} trades  {st['mean']:+.3f}R  CI [{st['lo']:+.3f}, {st['hi']:+.3f}]"
        f"  halves {st['first']:+.3f} / {st['second']:+.3f}  wins {100 * st['wins']:.0f}%{verdict}"
    )


def preregistered_checks(outcomes: list[TradeOutcome]) -> None:
    print("=" * 60)
    print("PRE-REGISTERED CHECKS (docs/research-log.md, 2026-11-03) - net R, managed stops")
    print("A rule PASSES only if its CI is entirely above zero AND both halves are positive.\n")
    print("  H1 - by the hour (UTC) the breakout bar opened:")
    for hour in (7, 8, 9, 10):
        _subset_line(f"{hour:02d}:00 bar", [o for o in outcomes if o.entry_time.hour == hour])
    other = [o for o in outcomes if o.entry_time.hour not in (7, 8, 9, 10)]
    if other:
        _subset_line("any other hour", other)
    print("\n  H2 - by commission as a share of the risk:")
    _subset_line("under 0.08R", [o for o in outcomes if o.commission_r < 0.08])
    _subset_line("0.08R - 0.12R", [o for o in outcomes if 0.08 <= o.commission_r < 0.12])
    _subset_line("0.12R and over", [o for o in outcomes if o.commission_r >= 0.12])
    print("\n  The rules, judged:")
    first_hour = [o for o in outcomes if o.entry_time.hour == PREREG_FIRST_HOUR]
    cheap = [o for o in outcomes if o.commission_r < PREREG_COMMISSION_CAP]
    both = [o for o in first_hour if o.commission_r < PREREG_COMMISSION_CAP]
    _subset_line("H1: 07:00 bar only", first_hour, judged=True)
    _subset_line("H2: commission < 0.08R only", cheap, judged=True)
    _subset_line("H1 + H2 together", both, judged=True)
    _subset_line("(every trade, for reference)", outcomes)
    print()


def main() -> None:
    keys = sorted(PLUGIN_REGISTRY["strategy"])
    if len(sys.argv) < 2:
        print("usage: python scripts/backtest.py <strategy_key> [symbol]")
        print(f"registered strategies: {', '.join(keys)}")
        print("\nPassing a symbol restricts the run to it AND gives you its own")
        print("first-half/second-half split - which is how you interrogate a")
        print("single promising symbol instead of admiring it.")
        raise SystemExit(2)

    key = sys.argv[1]
    if key not in keys:
        print(f"unknown strategy '{key}'. registered: {', '.join(keys)}")
        raise SystemExit(2)
    only_symbol = sys.argv[2].upper() if len(sys.argv) > 2 else None

    settings = Settings()
    # Built through the registry, so this screens ANY strategy the live engine
    # can run - same class, same code path, no separate backtest-only variant to
    # drift out of sync with what actually trades.
    strategy = load_plugin("strategy", key, settings)

    manager = StopManager(settings)
    broker = MT5BrokerAdapter(settings)
    broker.connect()  # blank MT5_LOGIN -> read-only attach, no session bump
    md = MT5MarketDataProvider(settings)

    # History is stamped per bar by the New-York-close rule (get_history), which
    # is only valid if the broker's clock follows it. Checked once here so a
    # mismatch stops the run with a reason, rather than skipping every symbol.
    from datetime import datetime, timezone

    from engine.plugins.brokers.mt5_time import follows_ny_close, ny_close_offset_seconds
    measured = md._offset()
    if not follows_ny_close(measured, datetime.now(timezone.utc)):
        print(f"STOP: the broker's UTC offset is {measured / 3600:+.2f}h now, but the New-York-close rule says "
              f"{ny_close_offset_seconds(datetime.now(timezone.utc)) / 3600:+.2f}h. Historical bars cannot be "
              f"given their correct hours, and session strategies would be tested an hour off.")
        raise SystemExit(2)
    print(f"Broker clock: UTC{measured / 3600:+.0f}h now, New-York-close convention confirmed - "
          f"every historical bar gets the offset in force when it formed.\n")

    # resolve_costs() takes ONE live spread snapshot and applies it to years of
    # trades. If the market is shut, bid==ask and that snapshot reads zero -
    # which silently understates cost. Say so rather than quietly flattering the
    # result.
    probe = mt5.symbol_info_tick("EURUSD")
    if probe is not None and probe.ask - probe.bid <= 0:
        print(
            "WARNING: EURUSD bid == ask - the market looks closed, so the spread\n"
            "         snapshot reads ~zero and SPREAD cost is UNDERSTATED here.\n"
            "         Commission still applies. Re-run during market hours for the\n"
            "         full picture; a strategy that loses on commission alone is\n"
            "         already answered.\n"
        )

    symbols = strategy.instruments
    if only_symbol is not None:
        if only_symbol not in symbols:
            print(f"'{only_symbol}' is not in {strategy.name}'s instruments: {', '.join(symbols)}")
            raise SystemExit(2)
        symbols = (only_symbol,)
        print(
            f"NOTE: restricted to {only_symbol}. If you are here because this symbol looked\n"
            f"      good in a 16-symbol run, remember that was 1 of 48 tests - roughly the\n"
            f"      rate at which pure noise manufactures a 'winner'. The half-split below\n"
            f"      is the question that matters: does it hold in BOTH halves?\n"
        )

    # Fail loudly on a timeframe we can't serve. The old version silently fed
    # every strategy H1+H4, so range_fade_h4_v1 (which wants D1) starved on every
    # bar and printed "no trades" - indistinguishable from an idea that simply
    # never triggers. A tool that reports nothing when it is broken is worse than
    # one that crashes.
    unsupported = [tf for tf in strategy.required_timeframes if tf not in WINDOW or tf not in TF_HOURS]
    if unsupported:
        print(f"cannot backtest '{key}': no window/step configured for "
              f"{', '.join(tf.value for tf in unsupported)}")
        print(f"supported: {', '.join(tf.value for tf in WINDOW)}")
        raise SystemExit(2)

    tfs = "  ".join(
        f"{tf.value}({WINDOW[tf]})" for tf in strategy.required_timeframes
    )
    print(f"Backtesting '{strategy.name}' over {len(symbols)} instrument(s)")
    print(f"  entry {strategy.required_timeframes[0].value}  ·  timeframes {tfs}\n")
    all_outcomes: list[TradeOutcome] = []
    print("Per-instrument (net of costs):\n")
    for symbol in symbols:
        try:
            outcomes = run_backtest_for_symbol(strategy, md, symbol, manager)
        except Exception as exc:
            # One unavailable symbol must not sink the whole screening run.
            print(f"{symbol}: skipped ({type(exc).__name__}: {exc})\n")
            continue
        all_outcomes.extend(outcomes)
        summarize(symbol, outcomes)

    broker.disconnect()

    if not all_outcomes:
        print("No signals produced over the available history - nothing to evaluate.")
        return

    all_outcomes.sort(key=lambda o: o.entry_time)
    span = f"{all_outcomes[0].entry_time}  ->  {all_outcomes[-1].entry_time}"
    years = max((all_outcomes[-1].entry_time - all_outcomes[0].entry_time).days / 365.25, 0.01)
    per_year = len(all_outcomes) / years
    print("=" * 60)
    print(f"History span of signals: {span}")
    print(f"Commission assumed: ${COMMISSION_PER_LOT_ROUNDTURN:.2f} round-turn per 1.0 lot on FX and metals, "
          f"none on indices, energies and crypto (as this account's deals show)")
    # Trade rate is a first-class result: a strategy that can't produce enough
    # trades to be judged can never earn a READY verdict, however good it looks.
    print(f"Trade rate: {per_year:.0f}/year  ->  ~{100 / per_year:.1f} years to reach 100 live trades\n")

    print(f"Stop management (as the engine trades): stop to entry at +{settings.breakeven_at_r:g}R, "
          f"trailing {settings.trail_distance_r:g}R behind past +{settings.trail_start_r:g}R"
          f"{'' if settings.trail_enabled else '  [DISABLED in Settings - stops held fixed]'}\n")
    summarize("ALL INSTRUMENTS", all_outcomes)

    # The same signals with every stop held where the strategy put it: the model
    # behind every backtest number recorded before 2026-10-12. Same trades, same
    # costs - the only difference is what happens once the stop could move.
    fixed = [o.as_fixed() for o in all_outcomes]
    summarize("ALL INSTRUMENTS, stops held FIXED (the pre-2026-10-12 model)", fixed)
    differ = sum(1 for o in all_outcomes if o.result != o.fixed_result)
    managed_e = sum(o.net_r for o in all_outcomes) / len(all_outcomes)
    fixed_e = sum(o.net_r for o in fixed) / len(fixed)
    print(f"Managed vs fixed: {differ} of {len(all_outcomes)} trades end differently; "
          f"expectancy {managed_e:+.3f}R vs {fixed_e:+.3f}R ({managed_e - fixed_e:+.3f}R per trade)\n")

    mid = len(all_outcomes) // 2
    print("Chronological stability (does the edge persist across time?):\n")
    summarize("  first half", all_outcomes[:mid])
    summarize("  second half", all_outcomes[mid:])

    print("Caveats - read before trusting any number above:")
    print("  - Costs use a live spread SNAPSHOT; real spreads widen at news/rollover.")
    print("  - Commission is an assumption (COMMISSION_PER_LOT_ROUNDTURN) - set it to your schedule.")
    print("  - Intrabar order is unknown; same-bar stop+target counts as a loss (conservative).")
    print("  - Stops are managed once per entry-timeframe bar, after its worst price; the engine checks every 5s.")
    print("  - Overnight financing uses TODAY's swap rates for every year; rates and their sign have changed.")
    print("  - Index prices fall on ex-dividend days and the CFD credits a long for it; that credit is not modelled.")
    print("  - One broker, one account, one historical path. Demo spreads differ from live.")
    print("  - Parameters were NOT optimised here, but this is still in-sample, not walk-forward.")
    print("  - A positive, tight, above-zero CI means 'worth forward-testing', not 'guaranteed'.")
    print()
    if key.startswith("london_breakout"):
        preregistered_checks(all_outcomes)  # hour and commission: that strategy's own test
    groups = getattr(strategy, "report_groups", None)
    if groups:
        grouped_report(all_outcomes, groups)


def grouped_report(outcomes: list[TradeOutcome], groups: dict[str, tuple[str, ...]]) -> None:
    """The breakdowns a strategy's pre-registration names (`report_groups`:
    label -> symbols), plus long against short. Net R, managed stops. Only the
    whole is judged; the parts are printed so the result can be read, not so a
    part can be kept."""
    print("=" * 60)
    print("PRE-REGISTERED VERDICT - net R, managed stops, after spread, commission and financing")
    print("PASS only if the CI is entirely above zero AND both chronological halves are positive.\n")
    _subset_line("every trade", outcomes, judged=True)
    print("\n  Read, not judged:")
    for label, symbols in groups.items():
        _subset_line(label, [o for o in outcomes if o.symbol in symbols])
    _subset_line("long", [o for o in outcomes if o.direction == Direction.LONG])
    _subset_line("short", [o for o in outcomes if o.direction == Direction.SHORT])
    gross = [o.gross_r for o in outcomes]
    print(f"\n  before any cost: {statistics.mean(gross):+.3f}R a trade;  spread+commission "
          f"{-statistics.mean(o.cost_r for o in outcomes):+.3f}R;  financing "
          f"{statistics.mean(o.swap_r for o in outcomes):+.3f}R")
    print()


if __name__ == "__main__":
    main()
