"""Trade-statistics primitives, shared by the offline backtest and the live
readiness evaluator so the two can never drift apart.

Everything here operates on plain lists of R-multiples (a trade's result divided
by the risk it took), which is what makes EURUSD and XAUUSD comparable at all.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20260713  # fixed so a given sample always yields the same CI


def max_drawdown_r(r_values: list[float]) -> float:
    """Largest peak-to-trough drop of the cumulative-R equity curve."""
    peak = 0.0
    equity = 0.0
    worst = 0.0
    for r in r_values:
        equity += r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def longest_losing_streak(r_values: list[float]) -> int:
    streak = 0
    longest = 0
    for r in r_values:
        if r < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest


def profit_factor(r_values: list[float]) -> float:
    gains = sum(r for r in r_values if r > 0)
    pains = -sum(r for r in r_values if r < 0)
    if pains <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / pains


def bootstrap_expectancy_ci(r_values: list[float]) -> tuple[float, float]:
    """95% CI on mean R/trade by resampling trades with replacement.

    This is the whole ballgame for "is there an edge?": if the interval straddles
    or sits below zero, the sample has NOT demonstrated one, however good the
    point estimate looks."""
    n = len(r_values)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        total = 0.0
        for _ in range(n):
            total += r_values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return (means[int(0.025 * BOOTSTRAP_ITERATIONS)], means[int(0.975 * BOOTSTRAP_ITERATIONS)])


@dataclass(frozen=True)
class TradeStats:
    """Everything needed to judge a strategy, computed from its R-multiples."""

    trades_count: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy_r: float | None
    ci_low: float | None
    ci_high: float | None
    profit_factor: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    max_drawdown_r: float | None
    longest_loss_streak: int
    total_net_pnl: float


def compute(r_values: list[float], net_pnl: float) -> TradeStats:
    n = len(r_values)
    if n == 0:
        return TradeStats(0, 0, 0, None, None, None, None, None, None, None, None, 0, 0.0)

    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    lo, hi = bootstrap_expectancy_ci(r_values)
    pf = profit_factor(r_values)
    return TradeStats(
        trades_count=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / n * 100.0),
        expectancy_r=sum(r_values) / n,
        ci_low=None if lo != lo else lo,  # nan -> None
        ci_high=None if hi != hi else hi,
        profit_factor=None if pf == float("inf") else pf,
        avg_win_r=statistics.mean(wins) if wins else None,
        avg_loss_r=statistics.mean(losses) if losses else None,
        max_drawdown_r=max_drawdown_r(r_values),
        longest_loss_streak=longest_losing_streak(r_values),
        total_net_pnl=net_pnl,
    )
