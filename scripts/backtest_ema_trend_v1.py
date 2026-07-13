"""Backtest + statistical evaluation for the ema_trend_v1 reference strategy.

Walks historical H1/H4 candles bar-by-bar through the exact same
EMATrendStrategy.evaluate() the live engine uses (same window sizes as
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

    python scripts/backtest_ema_trend_v1.py
"""

from __future__ import annotations

import random
import statistics
import sys
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import AccountState, Direction, Timeframe
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider
from engine.plugins.strategies.ema_trend_v1 import EMATrendStrategy

H1_WINDOW = 300  # matches engine/loop.py CANDLE_COUNT[H1]
H4_WINDOW = 250  # matches engine/loop.py CANDLE_COUNT[H4]
H1_HISTORY_BARS = 20_000  # ask for ~2.7 years of H1; broker caps what it returns
MAX_HOLD_BARS = 200  # give up on a trade that never resolves within ~8 trading days

# IC Markets "Raw Spread" charges commission separately from the (near-zero)
# spread: ~$3.50 per lot per side, i.e. ~$7 round-turn per 1.0 lot. Override
# here if your account's schedule differs. Expressed per 1.0 lot; the R-cost it
# produces is lot-size-independent (see _cost_in_r), so this stays valid no
# matter what lot the live risk engine actually sizes.
COMMISSION_PER_LOT_ROUNDTURN = 7.0

BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20260713  # fixed so the reported CI is reproducible run-to-run

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


def resolve_costs(symbol: str) -> SymbolCosts:
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"  WARNING: symbol_info({symbol}) is None - costs will be ignored for it")
        return SymbolCosts(spread_price=0.0, value_per_price_per_lot=0.0, available=False)
    spread_price = info.spread * info.point  # info.spread is a point count (snapshot)
    tick_size = info.trade_tick_size or info.point
    value_per_price = (info.trade_tick_value / tick_size) if tick_size else 0.0
    return SymbolCosts(
        spread_price=spread_price,
        value_per_price_per_lot=value_per_price,
        available=True,
    )


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
    strategy: EMATrendStrategy, md: MT5MarketDataProvider, symbol: str
) -> list[TradeOutcome]:
    h1_all = md.get_candles(symbol, Timeframe.H1, H1_HISTORY_BARS)[:-1]  # drop forming bar
    h4_all = md.get_candles(symbol, Timeframe.H4, H1_HISTORY_BARS // 4 + H4_WINDOW)[:-1]
    h4_times = [c.time for c in h4_all]
    costs = resolve_costs(symbol)

    outcomes: list[TradeOutcome] = []
    last_signal_index = -(10**9)

    # stop at len-2: a signal on bar i needs bar i+1 to exist to fill the entry
    for i in range(H1_WINDOW, len(h1_all) - 2):
        h1_window = h1_all[i - H1_WINDOW : i + 1]
        as_of = h1_window[-1].time

        h4_end = bisect_right(h4_times, as_of)
        h4_window = h4_all[max(0, h4_end - H4_WINDOW) : h4_end]
        if len(h4_window) < H4_WINDOW:
            continue

        context = StrategyContext(
            symbol=symbol,
            candles_by_timeframe={Timeframe.H1: h1_window, Timeframe.H4: h4_window},
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
        entry_fill = h1_all[i + 1].open
        risk_price = abs(entry_fill - signal.stop_loss)
        if risk_price <= 0:
            continue

        result, gross_r = simulate_outcome(
            signal.direction, entry_fill, signal.stop_loss, signal.take_profit, h1_all[i + 2 :]
        )
        net_r = gross_r - cost_in_r(costs, risk_price)
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
                net_r=net_r,
            )
        )
    return outcomes


# --- statistics -------------------------------------------------------------


def max_drawdown_r(net_rs: list[float]) -> float:
    """Largest peak-to-trough drop of the cumulative-R equity curve."""
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for r in net_rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def longest_losing_streak(outcomes: list[TradeOutcome]) -> int:
    streak = 0
    longest = 0
    for o in outcomes:
        if o.net_r < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest


def bootstrap_expectancy_ci(net_rs: list[float]) -> tuple[float, float]:
    """95% CI on mean R/trade by resampling trades with replacement. If this
    interval straddles or sits below zero, the sample hasn't demonstrated a
    real edge, however pretty the point estimate looks."""
    n = len(net_rs)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [net_rs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * BOOTSTRAP_ITERATIONS)]
    hi = means[int(0.975 * BOOTSTRAP_ITERATIONS)]
    return (lo, hi)


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
    print(f"  max drawdown     {max_drawdown_r(net_rs):.2f}R")
    print(f"  longest losing   {longest_losing_streak(outcomes)} in a row")
    print(f"  expectancy 95%CI [{lo:+.3f}, {hi:+.3f}] R/trade  -> edge {edge}")
    print()


def main() -> None:
    settings = Settings()
    broker = MT5BrokerAdapter(settings)
    broker.connect()  # blank MT5_LOGIN -> read-only attach, no session bump
    md = MT5MarketDataProvider(settings)
    strategy = EMATrendStrategy(settings)

    all_outcomes: list[TradeOutcome] = []
    print("Per-instrument (net of costs):\n")
    for symbol in strategy.instruments:
        outcomes = run_backtest_for_symbol(strategy, md, symbol)
        all_outcomes.extend(outcomes)
        summarize(symbol, outcomes)

    broker.disconnect()

    if not all_outcomes:
        print("No signals produced over the available history - nothing to evaluate.")
        return

    all_outcomes.sort(key=lambda o: o.entry_time)
    span = f"{all_outcomes[0].entry_time}  ->  {all_outcomes[-1].entry_time}"
    print("=" * 60)
    print(f"History span of signals: {span}")
    print(f"Commission assumed: ${COMMISSION_PER_LOT_ROUNDTURN:.2f} round-turn per 1.0 lot\n")

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
