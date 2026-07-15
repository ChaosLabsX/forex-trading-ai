from __future__ import annotations

from engine.plugins.strategies._common import TRENDING_UNIVERSE
from engine.plugins.strategies.donchian_breakout_v1 import DonchianBreakoutStrategy


class DonchianTrendingStrategy(DonchianBreakoutStrategy):
    """The same Donchian logic, pointed at trending assets instead of FX.

    This is an OUT-OF-SAMPLE TEST, not a new idea. It subclasses rather than
    copies for one reason: the logic must be provably identical. Every
    parameter - channel length, ATR stop, 1.5/3.0 asymmetry, session window -
    is inherited untouched. Nothing here was tuned, because nothing here CAN be
    tuned. Only the instrument list differs.

    That matters. Across 3 strategies x 16 symbols = 48 tests, exactly one came
    back positive (XAUUSD/donchian) - and noise alone is expected to manufacture
    ~2.4 false positives at 95% confidence, so finding one is FEWER than chance
    predicts. Re-running that same symbol, or writing a fresh strategy with
    fresh knobs until something passes, would only mine the noise harder.

    The only honest move left is a prediction about data nobody has looked at.
    The mechanism - trending assets carry persistent directional flow; FX majors
    are relative prices between similar economies and mean-revert - says
    momentum should work on silver, platinum, palladium, gas, bitcoin and
    European indices. If it does, that is evidence. If it does not, the gold
    result was noise and we stop.

    Read the eight non-gold symbols. XAUUSD is included because it genuinely
    belongs in a trending-asset strategy, but it is where the hypothesis came
    from - it is the control, and it proves nothing.
    """

    name = "donchian_trending_v1"
    instruments = TRENDING_UNIVERSE
