"""Objective readiness verdicts for every strategy, from real closed trades.

The rule that matters: a strategy is READY only when a bootstrap 95% confidence
interval on its expectancy sits *entirely above zero* on a large-enough sample.
A flattering point estimate on 12 trades is noise, and this refuses to call it
anything else. The same evaluation runs continuously, so a strategy that decays
loses its Ready status automatically - promotion is not permanent.

Verdicts are always derived from the DEMO lab's trades. Live results are still
evaluated and stored for display, but never feed the verdict: judging a strategy
by the account it was allowed onto would be circular.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from engine import stats as stats_mod
from engine.config import Settings
from engine.stats import TradeStats
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.evaluator")

NOT_READY = "not_ready"
ALMOST_READY = "almost_ready"
READY = "ready"


@dataclass(frozen=True)
class Evaluation:
    strategy_name: str
    account_key: str
    stats: TradeStats
    verdict: str
    reason: str


def classify(stats: TradeStats, settings: Settings) -> tuple[str, str]:
    """Verdict + a reason a human can act on. Ordered so the *binding*
    constraint is always what gets reported."""
    n = stats.trades_count
    min_a = settings.readiness_min_trades_almost
    min_r = settings.readiness_min_trades_ready

    if n < min_a:
        return NOT_READY, (
            f"only {n} closed trades with recorded risk - need at least {min_a} "
            f"before any verdict is statistically meaningful"
        )

    drawdown = stats.max_drawdown_r or 0.0
    if drawdown > settings.readiness_max_drawdown_r:
        return NOT_READY, (
            f"max drawdown {drawdown:.1f}R exceeds the {settings.readiness_max_drawdown_r:.0f}R limit"
        )

    expectancy = stats.expectancy_r or 0.0
    low, high = stats.ci_low, stats.ci_high
    ci_text = f"95% CI [{low:+.3f}, {high:+.3f}]" if low is not None else "CI unavailable"

    if expectancy <= 0:
        return NOT_READY, (
            f"expectancy {expectancy:+.3f}R/trade is not positive over {n} trades ({ci_text})"
        )

    proven = low is not None and low > 0
    enough = n >= min_r
    profit_factor = stats.profit_factor
    pf_ok = profit_factor is None or profit_factor >= settings.readiness_min_profit_factor
    pf_text = f"{profit_factor:.2f}" if profit_factor is not None else "n/a"

    if proven and enough and pf_ok:
        return READY, (
            f"{n} trades, expectancy {expectancy:+.3f}R, {ci_text} entirely above zero, "
            f"profit factor {pf_text}"
        )

    missing = []
    if not enough:
        missing.append(f"{n}/{min_r} trades")
    if not proven:
        missing.append(f"{ci_text} still includes zero")
    if not pf_ok:
        missing.append(f"profit factor {pf_text} < {settings.readiness_min_profit_factor}")
    return ALMOST_READY, f"expectancy {expectancy:+.3f}R is positive but " + "; ".join(missing)


class ReadinessEvaluator:
    """Recomputes every strategy's stats and verdict from Supabase.

    `on_change` is called with (strategy_row, previous, evaluation) whenever a
    verdict actually moves, so the caller can notify - the evaluator itself
    stays free of notification concerns."""

    def __init__(self, supabase: SupabaseClient, settings: Settings) -> None:
        self._supabase = supabase
        self._settings = settings

    def run(self, on_change=None) -> list[Evaluation]:
        try:
            accounts = self._supabase.select("accounts", {})
            strategies = self._supabase.select("strategies", {})
        except Exception:
            logger.exception("evaluator could not read registries")
            return []

        results: list[Evaluation] = []
        for account in accounts:
            for strategy in strategies:
                evaluation = self._evaluate(strategy["name"], account["key"])
                if evaluation is None:
                    continue
                results.append(evaluation)
                self._persist_snapshot(evaluation)
                # Only the lab's verdict is authoritative.
                if account["account_type"] == "demo":
                    self._apply_verdict(strategy, evaluation, on_change)
        return results

    def _evaluate(self, strategy_name: str, account_key: str) -> Evaluation | None:
        try:
            rows = self._supabase.select(
                "trades",
                {
                    "status": "eq.CLOSED",
                    "strategy_name": f"eq.{strategy_name}",
                    "account_key": f"eq.{account_key}",
                    "order": "closed_at.asc",
                },
            )
        except Exception:
            logger.exception("failed to load trades for %s/%s", strategy_name, account_key)
            return None

        r_values: list[float] = []
        net = 0.0
        for row in rows:
            pnl = row.get("realized_pnl")
            risk = row.get("risk_amount")
            if pnl is None:
                continue
            net += float(pnl)
            # Trades opened before risk_amount existed can't be expressed in R
            # and are excluded rather than guessed at.
            if risk:
                r_values.append(float(pnl) / float(risk))

        computed = stats_mod.compute(r_values, net)
        verdict, reason = classify(computed, self._settings)
        return Evaluation(strategy_name, account_key, computed, verdict, reason)

    def _persist_snapshot(self, evaluation: Evaluation) -> None:
        s = evaluation.stats
        try:
            self._supabase.insert(
                "strategy_evaluations",
                [
                    {
                        "strategy_name": evaluation.strategy_name,
                        "account_key": evaluation.account_key,
                        "trades_count": s.trades_count,
                        "wins": s.wins,
                        "losses": s.losses,
                        "win_rate": s.win_rate,
                        "expectancy_r": s.expectancy_r,
                        "ci_low": s.ci_low,
                        "ci_high": s.ci_high,
                        "profit_factor": s.profit_factor,
                        "avg_win_r": s.avg_win_r,
                        "avg_loss_r": s.avg_loss_r,
                        "max_drawdown_r": s.max_drawdown_r,
                        "longest_loss_streak": s.longest_loss_streak,
                        "total_net_pnl": s.total_net_pnl,
                        "verdict": evaluation.verdict,
                        "verdict_reason": evaluation.reason,
                    }
                ],
            )
        except Exception:
            logger.exception("failed to store evaluation snapshot for %s", evaluation.strategy_name)

    def _apply_verdict(self, strategy: dict, evaluation: Evaluation, on_change) -> None:
        previous = strategy.get("readiness")
        if previous == evaluation.verdict:
            return
        try:
            self._supabase.update(
                "strategies",
                {"name": f"eq.{evaluation.strategy_name}"},
                {
                    "readiness": evaluation.verdict,
                    "readiness_reason": evaluation.reason,
                    "readiness_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            logger.exception("failed to update readiness for %s", evaluation.strategy_name)
            return

        logger.info(
            "READINESS CHANGED: %s %s -> %s (%s)",
            evaluation.strategy_name, previous, evaluation.verdict, evaluation.reason,
        )
        if on_change is not None:
            try:
                on_change(strategy, previous, evaluation)
            except Exception:
                logger.exception("readiness change handler failed")
