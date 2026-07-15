from __future__ import annotations

from engine.core.models import Timeframe
from engine.plugins.strategies.range_fade_v1 import RangeFadeStrategy


class RangeFadeH4Strategy(RangeFadeStrategy):
    """The same fade, one scale up. A COST test, not a new idea.

    range_fade_v1 is the most important result this project has produced: over
    6,033 trades it made **+264.78R gross**, and costs took 425.55R of it. Doing
    the arithmetic the first read skipped - net expectancy -0.027R with a CI of
    [-0.058, +0.004] implies a standard error near 0.016, so the GROSS
    expectancy of +0.044R/trade carries a CI of roughly [+0.013, +0.075].
    Entirely above zero. The mean-reversion signal is real. It is simply smaller
    than the toll charged to trade it.

    That turns the problem from "find an edge" into "pay less for the one we
    have". Cost in R is commission / (stop x value), so it falls as the stop
    grows: the identical signal on an H4 bar risks roughly twice as much per
    trade and therefore carries roughly half the cost drag. Needed: costs under
    ~0.03R against a measured 0.066R. H4 is arithmetically in range.

    Nothing is tuned. `evaluate()` is inherited untouched - same bands, same
    ADX gate, same stop and target multiples - and only the timeframes move.
    That is deliberate: with a real gross edge in hand, the temptation to twiddle
    parameters until the net turns positive is exactly how a false positive gets
    funded. This makes one prediction instead: if the edge is scale-invariant,
    it survives at H4 with the costs halved. If it does not, the edge lives only
    at H1, where it is unaffordable, and that is a real answer too.

    The honest risk: mean reversion at one hour and at four hours are not
    guaranteed to be the same phenomenon. This test can fail for that reason
    alone, and that failure would be informative rather than disappointing.
    """

    name = "range_fade_h4_v1"
    entry_tf = Timeframe.H4
    regime_tf = Timeframe.D1
    required_timeframes = (Timeframe.H4, Timeframe.D1)
