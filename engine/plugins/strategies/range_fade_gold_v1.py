from __future__ import annotations

from engine.plugins.strategies.range_fade_v1 import RangeFadeStrategy


class RangeFadeGoldStrategy(RangeFadeStrategy):
    """range_fade_v1, unchanged, on gold alone. A test of a cost argument.

    range_fade_v1 is the one signal in this log that predicts price before
    costs, measured twice on different markets: +0.041R a trade gross on FX,
    +0.048R on six stock indices. Both times a ~0.07R toll took it. Gold is
    where that toll is smallest here: its spread and commission are fixed in
    dollars while its hourly range tripled with its price, so a 1-ATR H1 stop
    cost ~0.06R in 2017-2019, ~0.03R in 2020-2024 and ~0.01R in 2025-2026
    (scripts/backtest.py's cost model, measured 2026-11-19 before any run).

    The owner asked for a gold strategy. This is the gold strategy the
    evidence supports: the one real signal, on the market where it is
    cheapest - not a new pattern fitted to gold.

    Nothing is tuned. `evaluate()` is the parent's own function (asserted in
    scripts/test_range_fade_gold.py). Only the instrument list differs.
    Registered for backtests; not in config/plugins.yaml unless it passes its
    pre-registered test (docs/research-log.md, 2026-11-19).
    """

    name = "range_fade_gold_v1"
    instruments = ("XAUUSD",)
    # Gold's real hourly history here starts 2016-01; ask for all of it (the
    # terminal refuses a count equal to its 100,000 "max bars": one under).
    backtest_history_bars = 99_999
