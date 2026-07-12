"""Phase 2 sanity-check backtest for the ema_trend_v1 reference strategy.

Walks historical H1/H4 candles bar-by-bar through the exact same
EMATrendStrategy.evaluate() the live engine uses (same window sizes as
engine/loop.py's CANDLE_COUNT), then simulates each fired signal forward to see
whether its stop-loss or take-profit would have been hit first.

This is a "results are sane, logic isn't obviously broken" check, not a
statistically rigorous strategy validation - PLAN.md's bar for Phase 2 exit.

    python scripts/backtest_ema_trend_v1.py
"""

from __future__ import annotations

import sys
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import AccountState, Direction, Timeframe
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider
from engine.plugins.strategies.ema_trend_v1 import EMATrendStrategy

H1_WINDOW = 300  # matches engine/loop.py CANDLE_COUNT[H1]
H4_WINDOW = 250  # matches engine/loop.py CANDLE_COUNT[H4]
H1_HISTORY_BARS = 4000  # ~5.5 months of H1 bars
MAX_HOLD_BARS = 200  # give up on a trade that never resolves within ~8 days

PLACEHOLDER_ACCOUNT = AccountState(
    balance=10_000.0,
    equity=10_000.0,
    margin_used=0.0,
    open_positions_count=0,
    daily_pnl=0.0,
    consecutive_stop_losses_today=0,
)


@dataclass
class TradeOutcome:
    symbol: str
    direction: Direction
    entry_time: object
    entry_price: float
    stop_loss: float
    take_profit: float
    result: str  # "win" | "loss" | "timeout"
    r_multiple: float


def simulate_outcome(direction: Direction, entry_price: float, stop_loss: float, take_profit: float, future_bars) -> tuple[str, float]:
    risk = abs(entry_price - stop_loss)
    for bar in future_bars[:MAX_HOLD_BARS]:
        hit_stop = bar.low <= stop_loss if direction == Direction.LONG else bar.high >= stop_loss
        hit_target = bar.high >= take_profit if direction == Direction.LONG else bar.low <= take_profit
        if hit_stop:  # conservative: assume stop resolves first if both touch in the same bar
            return "loss", -1.0
        if hit_target:
            reward = abs(take_profit - entry_price)
            return "win", reward / risk if risk else 0.0
    return "timeout", 0.0


def run_backtest_for_symbol(strategy: EMATrendStrategy, md: MT5MarketDataProvider, symbol: str) -> list[TradeOutcome]:
    h1_all = md.get_candles(symbol, Timeframe.H1, H1_HISTORY_BARS)[:-1]  # drop forming bar
    h4_all = md.get_candles(symbol, Timeframe.H4, H1_HISTORY_BARS // 4 + H4_WINDOW)[:-1]
    h4_times = [c.time for c in h4_all]

    outcomes: list[TradeOutcome] = []
    last_signal_index = -10**9

    for i in range(H1_WINDOW, len(h1_all) - 1):
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
        result, r_multiple = simulate_outcome(
            signal.direction, signal.entry_price, signal.stop_loss, signal.take_profit, h1_all[i + 1 :]
        )
        outcomes.append(
            TradeOutcome(
                symbol=symbol,
                direction=signal.direction,
                entry_time=as_of,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                result=result,
                r_multiple=r_multiple,
            )
        )
    return outcomes


def main() -> None:
    settings = Settings()
    broker = MT5BrokerAdapter(settings)
    broker.connect()
    md = MT5MarketDataProvider(settings)
    strategy = EMATrendStrategy(settings)

    all_outcomes: list[TradeOutcome] = []
    for symbol in strategy.instruments:
        outcomes = run_backtest_for_symbol(strategy, md, symbol)
        all_outcomes.extend(outcomes)
        wins = sum(1 for o in outcomes if o.result == "win")
        losses = sum(1 for o in outcomes if o.result == "loss")
        timeouts = sum(1 for o in outcomes if o.result == "timeout")
        resolved = wins + losses
        win_rate = (wins / resolved * 100) if resolved else 0.0
        total_r = sum(o.r_multiple for o in outcomes if o.result != "timeout")
        print(
            f"{symbol}: {len(outcomes)} signals | {wins}W/{losses}L/{timeouts} timeout | "
            f"win rate {win_rate:.1f}% | total R {total_r:+.2f}"
        )

    broker.disconnect()

    print()
    print("Sample signals:")
    for o in all_outcomes[:10]:
        print(f"  {o.entry_time} {o.symbol} {o.direction.value} @ {o.entry_price:.5f} -> {o.result} ({o.r_multiple:+.2f}R)")


if __name__ == "__main__":
    main()
