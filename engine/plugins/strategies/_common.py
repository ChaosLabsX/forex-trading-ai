"""Shared building blocks for strategy plugins.

The instrument universe and the news blackout are identical across strategies
and have no business being copy-pasted: a currency added here must apply
everywhere, and a blackout bug fixed once must be fixed everywhere.
"""

from __future__ import annotations

from datetime import datetime

from engine.core.interfaces.strategy import StrategyContext
from engine.core.models import Candle, PositionStatus

# 16 FX majors/crosses + gold. Breadth is a data-rate decision, not an edge
# claim: the lab needs ~100 closed trades before it will render a verdict, so a
# strategy watching 4 symbols waits years to be judged.
#
# These are NOT independent samples - EURUSD, GBPUSD and EURGBP share drivers,
# so correlated signals inflate the apparent sample size and the bootstrap CI
# (which assumes independence) reads slightly tighter than reality. A real
# limitation, and still far better than being unjudgeable.
INSTRUMENT_CURRENCIES: dict[str, tuple[str, ...]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("USD",),
    "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "USDCHF": ("USD", "CHF"),
    "NZDUSD": ("NZD", "USD"),
    "EURJPY": ("EUR", "JPY"),
    "GBPJPY": ("GBP", "JPY"),
    "EURGBP": ("EUR", "GBP"),
    "AUDJPY": ("AUD", "JPY"),
    "EURAUD": ("EUR", "AUD"),
    "GBPAUD": ("GBP", "AUD"),
    "CADJPY": ("CAD", "JPY"),
    "CHFJPY": ("CHF", "JPY"),
}

UNIVERSE: tuple[str, ...] = tuple(INSTRUMENT_CURRENCIES)

NEWS_BLACKOUT_MINUTES = 30


def news_blackout(
    context: StrategyContext, as_of: datetime, minutes: int = NEWS_BLACKOUT_MINUTES
) -> str | None:
    """Reason string if a high-impact event in one of this symbol's currencies
    falls within `minutes` either side of `as_of`; None if clear."""
    relevant = INSTRUMENT_CURRENCIES.get(context.symbol, ())
    for event in context.upcoming_news:
        if event.currency not in relevant or event.impact != "high":
            continue
        if abs((event.time - as_of).total_seconds()) / 60 <= minutes:
            return f"news blackout: {event.currency} '{event.title}' within {minutes}min"
    return None


def has_open_position(context: StrategyContext) -> bool:
    return any(
        p.symbol == context.symbol and p.status == PositionStatus.OPEN
        for p in context.open_positions
    )


def bars_today(candles: list[Candle], as_of: datetime, before_hour: int) -> list[Candle]:
    """Candles from as_of's UTC date with hour < before_hour."""
    return [c for c in candles if c.time.date() == as_of.date() and c.time.hour < before_hour]
