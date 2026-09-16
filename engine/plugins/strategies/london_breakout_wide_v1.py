from __future__ import annotations

from engine.plugins.strategies.london_breakout_v1 import LondonBreakoutStrategy


class LondonBreakoutWideStrategy(LondonBreakoutStrategy):
    """london_breakout_v1 with a looser compression limit: 1.75x ATR, not 1.5x.

    DEMO ONLY. One dimension moves and everything else is inherited: same 16
    symbols, same windows, same stop and target. Exists to answer one question
    for the owner: can this strategy trade more often without trading worse?

    What the limit does. The Asian range spans 7 hourly bars, so on an ordinary
    night it is typically 2-2.5x a single bar's ATR. 1.5x admits only quiet nights
    - 9% of symbol-days over 28 clean demo days. 1.75x admits 19%. That is a
    FREQUENCY count, taken before this was built; no outcome was looked at to
    choose the number.

    Pre-registered prediction (docs/research-log.md, 2026-09-16): about twice
    the trades, and a LOWER per-trade result than 1.5x - the extra setups come
    from less-compressed nights, which the premise says carry less edge. It is
    worth anything only if it stays positive after costs.

    1.75 is chosen once and is final. If it disappoints, the answer is 1.5x or
    nothing - not 2.0, then 2.25, until one looks good. Trying values until one
    wins is the mining the standing rule forbids, and the winner it finds is the
    one that loses real money.

    It fires on every setup london_breakout_v1 fires on, plus the looser ones, so
    the two records overlap. The informative trades are the ones v1 did not
    take - read those, not the headline.
    """

    name = "london_breakout_wide_v1"
    max_range_atr_multiple = 1.75
