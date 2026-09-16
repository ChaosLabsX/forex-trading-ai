from __future__ import annotations

from engine.plugins.strategies._common import LONDON_CROSSES
from engine.plugins.strategies.london_breakout_v1 import LondonBreakoutStrategy


class LondonBreakoutCrossesStrategy(LondonBreakoutStrategy):
    """The same London-open breakout, on five pairs it has never traded.

    An OUT-OF-SAMPLE TEST, not a new idea, and DEMO ONLY. It subclasses rather
    than copies so the logic is provably identical: the Asian window, the 1.5x
    compression limit, the fresh-break rule, the 1.0/1.5 ATR stop and target are
    all inherited untouched. Only the instrument list differs.

    Why these five (see LONDON_CROSS_CURRENCIES): the premise needs a quiet
    Asian session, which holds for EUR, GBP, CHF and CAD and fails for JPY, AUD
    and NZD. The pairs were picked by that rule before any result on them
    existed, so whatever they return is evidence rather than a selected winner.

    Pre-registered prediction (docs/research-log.md, 2026-09-16): roughly
    0.5-0.8 trades a day, and a per-trade result no better than
    london_breakout_v1's - crosses have wider spreads, and this strategy already
    pays the highest cost in the lab. If it is clearly worse, stop; do not start
    dropping the pairs that lost.

    Motivated by trade frequency: london_breakout_v1 averages ~1.1 trades a day
    and went three days without one on 2026-09-14 to 16.
    """

    name = "london_breakout_crosses_v1"
    instruments = LONDON_CROSSES
