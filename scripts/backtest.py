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
from dataclasses import dataclass
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyPlugin
from engine.core.models import AccountState, Direction, Timeframe
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
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
MAX_HOLD_BARS = 200  # give up on a trade that never resolves within ~8 trading days

# IC Markets "Raw Spread" charges commission separately from the (near-zero)
# spread: ~$3.50 per lot per side, i.e. ~$7 round-turn per 1.0 lot. Override
# here if your account's schedule differs. Expressed per 1.0 lot; the R-cost it
# produces is lot-size-independent (see _cost_in_r), so this stays valid no
# matter what lot the live risk engine actually sizes.
COMMISSION_PER_LOT_ROUNDTURN = 7.0

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


@dataclass
class TradeOutcome:
    symbol: str
    direction: Direction
    entry_time: object
    entry_price: float
    stop_loss: float
    take_profit: float
    result: str  # "win" | "loss" | "timeout"
    gross_r: float  # R before costs
    net_r: float  # R after spread + commission
    cost_r: float  # what costs took, so the model stays auditable
    risk_price: float


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
    return SymbolCosts(
        spread_price=spread_price,
        value_per_price_per_lot=value_per_price,
        min_stop_price=info.trade_stops_level * info.point,
        point=info.point,
        available=True,
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


def cost_in_r(costs: SymbolCosts, risk_price: float) -> float:
    """Round-trip cost of a trade, expressed as a fraction of 1R.

    spread is already in price units, so spread_R = spread / risk. commission is
    a fixed currency amount; dividing by (risk_price * value_per_price_per_lot)
    converts it to R and the lot size cancels out, so this holds for any lot."""
    if risk_price <= 0:
        return 0.0
    spread_r = costs.spread_price / risk_price
    commission_r = 0.0
    if costs.available and costs.value_per_price_per_lot > 0:
        commission_r = COMMISSION_PER_LOT_ROUNDTURN / (risk_price * costs.value_per_price_per_lot)
    return spread_r + commission_r


def simulate_outcome(
    direction: Direction,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    future_bars,
) -> tuple[str, float]:
    """Gross R (before costs) walking H1 bars forward from the entry.

    Conservative on intrabar order: if a single bar touches both stop and
    target, the stop is assumed to fill first. Timeouts mark to the last bar's
    close rather than being discarded - a trade left open for 8 days isn't a
    free scratch, it carries whatever P&L it had."""
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return "loss", -1.0
    last_close = entry_price
    for bar in future_bars[:MAX_HOLD_BARS]:
        last_close = bar.close
        hit_stop = bar.low <= stop_loss if direction == Direction.LONG else bar.high >= stop_loss
        hit_target = bar.high >= take_profit if direction == Direction.LONG else bar.low <= take_profit
        if hit_stop:
            return "loss", -1.0
        if hit_target:
            reward = abs(take_profit - entry_price)
            return "win", reward / risk
    # never resolved: mark to market at the last close we saw
    signed = (last_close - entry_price) if direction == Direction.LONG else (entry_price - last_close)
    return "timeout", signed / risk


def run_backtest_for_symbol(
    strategy: StrategyPlugin, md: MT5MarketDataProvider, symbol: str
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

    entry_all = md.get_candles(symbol, entry_tf, ENTRY_HISTORY_BARS)[:-1]  # drop forming bar
    if len(entry_all) <= entry_window + 2:
        return []

    # Ask each context timeframe for the SAME span of history the entry bars
    # cover, so a slower regime filter isn't starved on long runs.
    span_hours = len(entry_all) * TF_HOURS[entry_tf]
    context_bars: dict = {}
    context_times: dict = {}
    for tf in context_tfs:
        needed = int(span_hours / TF_HOURS[tf]) + WINDOW[tf] + 2
        bars = md.get_candles(symbol, tf, needed)[:-1]
        context_bars[tf] = bars
        context_times[tf] = [c.time for c in bars]

    costs = resolve_costs(symbol)

    outcomes: list[TradeOutcome] = []
    last_signal_index = -(10**9)
    floor = min_tradeable_stop(costs)
    untradeable = 0

    # stop at len-2: a signal on bar i needs bar i+1 to exist to fill the entry
    for i in range(entry_window, len(entry_all) - 2):
        window = entry_all[i - entry_window : i + 1]
        as_of = window[-1].time

        candles: dict = {entry_tf: window}
        starved = False
        for tf in context_tfs:
            # Only bars that had already CLOSED at as_of - taking any later bar
            # would leak the future into the decision.
            end = bisect_right(context_times[tf], as_of)
            sliced = context_bars[tf][max(0, end - WINDOW[tf]) : end]
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
            open_positions=[],
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

        result, gross_r = simulate_outcome(
            signal.direction, entry_fill, signal.stop_loss, signal.take_profit, entry_all[i + 2 :]
        )
        cost_r = cost_in_r(costs, risk_price)
        outcomes.append(
            TradeOutcome(
                symbol=symbol,
                direction=signal.direction,
                entry_time=as_of,
                entry_price=entry_fill,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                result=result,
                gross_r=gross_r,
                net_r=gross_r - cost_r,
                cost_r=cost_r,
                risk_price=risk_price,
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
    timeouts = [o for o in outcomes if o.result == "timeout"]
    resolved = len(wins) + len(losses)
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

    print(f"{label}:")
    print(f"  trades           {n}  ({len(wins)}W / {len(losses)}L / {len(timeouts)} timeout)")
    print(f"  win rate         {win_rate:.1f}%  (of resolved)")
    print(f"  total R          gross {gross_total:+.2f}   net {net_total:+.2f}   (costs cut {gross_total - net_total:.2f}R)")
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

    broker = MT5BrokerAdapter(settings)
    broker.connect()  # blank MT5_LOGIN -> read-only attach, no session bump
    md = MT5MarketDataProvider(settings)

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
            outcomes = run_backtest_for_symbol(strategy, md, symbol)
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
    print(f"Commission assumed: ${COMMISSION_PER_LOT_ROUNDTURN:.2f} round-turn per 1.0 lot")
    # Trade rate is a first-class result: a strategy that can't produce enough
    # trades to be judged can never earn a READY verdict, however good it looks.
    print(f"Trade rate: {per_year:.0f}/year  ->  ~{100 / per_year:.1f} years to reach 100 live trades\n")

    summarize("ALL INSTRUMENTS", all_outcomes)

    mid = len(all_outcomes) // 2
    print("Chronological stability (does the edge persist across time?):\n")
    summarize("  first half", all_outcomes[:mid])
    summarize("  second half", all_outcomes[mid:])

    print("Caveats - read before trusting any number above:")
    print("  - Costs use a live spread SNAPSHOT; real spreads widen at news/rollover.")
    print("  - Commission is an assumption (COMMISSION_PER_LOT_ROUNDTURN) - set it to your schedule.")
    print("  - Intrabar order is unknown; same-bar stop+target counts as a loss (conservative).")
    print("  - One broker, one account, one historical path. Demo spreads differ from live.")
    print("  - Parameters were NOT optimised here, but this is still in-sample, not walk-forward.")
    print("  - A positive, tight, above-zero CI means 'worth forward-testing', not 'guaranteed'.")


if __name__ == "__main__":
    main()
