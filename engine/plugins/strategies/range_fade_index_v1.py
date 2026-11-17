from __future__ import annotations

from engine.plugins.strategies._common import TREND_DAILY_GROUPS
from engine.plugins.strategies.range_fade_v1 import RangeFadeStrategy

# One stock index per region - the rule trend_daily_v1 fixed on 2026-11-13,
# before any result, reused here so the market list is not a fresh choice.
INDEX_UNIVERSE: tuple[str, ...] = TREND_DAILY_GROUPS["stock indices"]


class RangeFadeIndexStrategy(RangeFadeStrategy):
    """range_fade_v1, unchanged, on stock indices. An OUT-OF-SAMPLE test.

    range_fade_v1 is the only signal in this log that predicts price before
    costs: +0.041R a trade gross, CI [+0.011, +0.071], over 5,567 FX trades
    (re-measured 2026-11-14). It loses only because FX costs ~0.07R a trade,
    most of it the $7/lot commission. Stock-index CFDs here carry no
    commission (this account's own deals show it), so the toll is the spread
    alone.

    Two predictions, one test: if fading over-extension in a quiet regime is a
    general liquidity effect, it shows up on markets it has never seen, and
    there it is cheap enough to keep. If it is an FX-only effect, or noise
    that happened to clear zero, this fails - and that is a real answer.

    Nothing is tuned. `evaluate()` is the parent's own function (asserted in
    scripts/test_range_fade_index.py): same EMA, bands, ADX gate, stop, target
    and 07-20 UTC session. Only the instrument list differs. Registered for
    backtests; not in config/plugins.yaml unless it passes its pre-registered
    test (docs/research-log.md, 2026-11-17).
    """

    name = "range_fade_index_v1"
    instruments = INDEX_UNIVERSE
    # range_fade_v1's FX run saw ~3 years (20,000 H1 bars). Index intraday
    # history reaches back to ~2016; ask for all of it - the broker returns
    # what it has, and first_intraday_index drops daily-only years. The
    # terminal refuses a count equal to its "max bars" (100,000): one under.
    backtest_history_bars = 99_999
