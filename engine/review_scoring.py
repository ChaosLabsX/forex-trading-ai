"""Scores Claude's shadow-mode reviews against what the trades actually did.

Shadow mode's entire justification is building "a track record of its opinions
against real-money outcomes [that] could one day justify letting it gate trades"
(engine/plugins/ai/claude_ai_provider.py). Migration 0014 added the join key that
makes a review scoreable - `trades.signal_id` -> `signals.id`, the same key
`ai_reviews.signal_id` uses. This module is the thing that finally reads it.

The question it answers is narrow and falsifiable: **does Claude's approval
predict outcome?** If trades it approved and trades it rejected have the same
expectancy, its opinion carries no information and no amount of prose in the
rationale changes that.

The property that makes this measurable - and that a gating reviewer would
destroy - is that the verdict never blocks anything. RiskEngine decides; the
review is logged beside it. So BOTH arms are observed: approved and rejected
trades are all taken and all resolve. That is a randomised-ish trial you almost
never get in trading, and it exists only because the reviewer is powerless. The
moment it is allowed to gate, the rejected arm vanishes and the record can no
longer be extended - only spent.

Every number here is computed in code. The model is never asked to score itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from engine import stats as stats_mod
from engine.stats import TradeStats
from engine.supabase_client import SupabaseClient

logger = logging.getLogger("engine.review_scoring")

# How many recent closed trades to consider. Generous: the binding constraint is
# how many carry both a signal_id and a review, which is far fewer.
TRADE_FETCH_LIMIT = 500

# Below this many scored trades in an arm, the arm's expectancy is not reported
# as a number at all. Matches the spirit of readiness_min_trades_almost (30) -
# this project's standing position is that a point estimate on a dozen trades is
# noise wearing a decimal point.
MIN_ARM_FOR_ESTIMATE = 30


@dataclass(frozen=True)
class ReviewRecord:
    """Claude's shadow verdicts joined to realised R-multiples, split by verdict."""

    scored: int                 # trades carrying both a review and a usable outcome
    approved: TradeStats
    rejected: TradeStats

    @property
    def has_verdict(self) -> bool:
        """True when BOTH arms are thick enough for the comparison to mean anything.
        One arm of 200 and another of 3 is not a comparison."""
        return (
            self.approved.trades_count >= MIN_ARM_FOR_ESTIMATE
            and self.rejected.trades_count >= MIN_ARM_FOR_ESTIMATE
        )

    def summary_for_prompt(self) -> str:
        """Compact, honest rendering for the review prompt itself.

        Deliberately refuses to hand the model a flattering number early: until
        both arms clear MIN_ARM_FOR_ESTIMATE it reports only the sample size. A
        reviewer told "your approvals run +0.4R" on 11 trades learns to approve.
        """
        if self.scored == 0:
            return (
                "Your past verdicts have not been scored yet - no closed trade so far "
                "carries both a review and a recorded risk amount. Judge this signal "
                "on its own merits."
            )
        if not self.has_verdict:
            return (
                f"{self.scored} of your past verdicts have been scored so far "
                f"({self.approved.trades_count} approved, {self.rejected.trades_count} rejected). "
                f"That is too few in at least one arm to say whether your judgement adds "
                f"anything, so no performance figure is given - it would be noise, and "
                f"acting on it would make your reviews worse rather than better."
            )

        def arm(heading: str, s: TradeStats) -> str:
            ci = (
                f", 95% CI [{s.ci_low:+.3f}, {s.ci_high:+.3f}]"
                if s.ci_low is not None and s.ci_high is not None
                else ""
            )
            return f"- {heading}: {s.trades_count} trades, expectancy {s.expectancy_r:+.3f}R{ci}"

        gap = (self.approved.expectancy_r or 0.0) - (self.rejected.expectancy_r or 0.0)
        # Non-overlapping CIs is a conservative read of "these differ" - it is a
        # stricter bar than a formal test of the difference, which is the right
        # direction to err in.
        separated = (
            self.approved.ci_low is not None
            and self.rejected.ci_high is not None
            and self.approved.ci_low > self.rejected.ci_high
        )
        if separated:
            reading = (
                f"Your approvals outperform your rejections by {gap:+.3f}R/trade and the "
                f"intervals do not overlap - your judgement is carrying real information. "
                f"Keep applying the same standard."
            )
        else:
            reading = (
                f"The gap between the two arms is {gap:+.3f}R/trade, but the confidence "
                f"intervals overlap: on this evidence your approvals are NOT distinguishable "
                f"from your rejections. Your judgement has not yet been shown to add anything. "
                f"Be more discriminating - approving nearly everything produces exactly this "
                f"result."
            )
        return "\n".join([
            "YOUR OWN TRACK RECORD (computed from closed trades, not self-assessed):",
            arm("Trades you APPROVED", self.approved),
            arm("Trades you REJECTED (taken anyway - your verdict does not gate)", self.rejected),
            reading,
        ])


def _empty_stats() -> TradeStats:
    """Derived from stats.compute rather than hand-constructed, so adding a field
    to TradeStats can never leave a stale positional literal here."""
    return stats_mod.compute([], 0.0)


EMPTY_RECORD = ReviewRecord(scored=0, approved=_empty_stats(), rejected=_empty_stats())


def compute(supabase: SupabaseClient, account_key: str) -> ReviewRecord:
    """Join reviews to outcomes for one account. Never raises - a scoring failure
    must not take down the trading loop, and an empty record degrades to 'no
    verdict yet', which is the truthful thing to say when the join fails."""
    try:
        trades = supabase.select(
            "trades",
            {
                "status": "eq.CLOSED",
                "account_key": f"eq.{account_key}",
                "signal_id": "not.is.null",
                "select": "signal_id,realized_pnl,risk_amount,void_reason",
                "order": "closed_at.desc",
                "limit": str(TRADE_FETCH_LIMIT),
            },
        )
    except Exception:
        logger.exception("could not load trades for review scoring")
        return EMPTY_RECORD

    # R per signal, applying the same exclusions the readiness evaluator applies:
    # voided trades have an outcome nobody believes (migration 0013), and a trade
    # with no recorded risk cannot be expressed in R at all.
    r_by_signal: dict[int, float] = {}
    for row in trades:
        if row.get("void_reason"):
            continue
        pnl, risk = row.get("realized_pnl"), row.get("risk_amount")
        if pnl is None or not risk:
            continue
        signal_id = row.get("signal_id")
        if signal_id is not None:
            r_by_signal[int(signal_id)] = float(pnl) / float(risk)

    if not r_by_signal:
        return EMPTY_RECORD

    ids = sorted(r_by_signal)
    try:
        reviews = supabase.select(
            "ai_reviews",
            {
                "signal_id": f"in.({','.join(str(i) for i in ids)})",
                "select": "signal_id,approved",
            },
        )
    except Exception:
        logger.exception("could not load ai_reviews for scoring")
        return EMPTY_RECORD

    approved_r: list[float] = []
    rejected_r: list[float] = []
    for review in reviews:
        signal_id = review.get("signal_id")
        if signal_id is None:
            continue
        r = r_by_signal.get(int(signal_id))
        if r is None:
            continue
        (approved_r if review.get("approved") else rejected_r).append(r)

    return ReviewRecord(
        scored=len(approved_r) + len(rejected_r),
        approved=stats_mod.compute(approved_r, sum(approved_r)),
        rejected=stats_mod.compute(rejected_r, sum(rejected_r)),
    )
