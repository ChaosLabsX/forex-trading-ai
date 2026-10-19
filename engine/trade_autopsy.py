"""How a closed trade ended, and how far it went for and against us on the way.

Recorded on every closed trade (migration 0017) so "why do we lose?" can be
answered from data instead of from the losses that happen to be memorable:

  exit_reason      target | stop | breakeven | trailing_stop | manual | engine |
                   stop_out | other | unknown - from the broker's own closing deal
  exit_price       the fill of the closing deal
  max_favorable_r  the best price reached while open, in R of the INITIAL risk
                   (+0.8 = it was 0.8R in profit at its best; never below 0)
  max_adverse_r    the worst price reached, in R (-0.6 = 0.6R against at its
                   worst; never above 0)

What the pair says: a loss that never went positive is an entry problem; a loss
that reached +0.8R first is an exit problem; a winner that dipped to -0.9R
before winning was nearly a loss. Each is a hypothesis to test in
scripts/backtest.py - never a reason to change a live rule on its own. Reading
"what would have saved the last few losers" off this data and acting on it is
exactly the mining docs/research-log.md forbids.

Excursions come from the bid-price bars that lie WHOLLY inside the trade, plus
the fill and exit prices themselves. A bar that straddles the entry or the exit
is left out, because its high and low can't be split into before and after: the
first version kept them, and on 2026-10-13 a GBPJPY short filled 50 seconds
into the minute, after a 14-pip bounce, was credited with that bounce (+2.3R
"best" on a trade that never got near +1R). Leaving them out can miss an extreme
inside those partial minutes, so the figures lean conservative. A short's stop
fills at the ask while the bars are bids; coarser bars on older backfilled
trades widen both effects.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from engine.core.models import Candle, Timeframe

EXIT_LABELS = {
    "target": "hit target",
    "stop": "full stop",
    "breakeven": "stop at entry",
    "trailing_stop": "trailing stop",
    "manual": "closed by hand",
    "engine": "closed by the engine",
    "stop_out": "broker stop-out",
}

_TF_MINUTES = {Timeframe.M1: 1, Timeframe.M5: 5, Timeframe.M15: 15, Timeframe.H1: 60}
# The broker returns at most this many bars per request (MT5's chart default).
MAX_BARS = 99_000


def _is_long(direction) -> bool:
    return str(getattr(direction, "value", direction)).upper() == "LONG"


def price_r(direction, entry: float, risk: float, price: float) -> float:
    """Where `price` sits relative to entry, in R. Positive is profit."""
    signed = (price - entry) if _is_long(direction) else (entry - price)
    return signed / risk


def classify_exit(direction, entry: float, initial_stop: float, exit_price: float | None,
                  exit_how: str | None) -> str:
    """The trade's ending, in words a person would use.

    A stop-loss fill is split by where it filled: near the original stop is a
    full stop; at or near entry means the stop had been moved to breakeven; well
    beyond entry means a trailing stop locked in profit."""
    if exit_how == "tp":
        return "target"
    if exit_how == "client":
        return "manual"
    if exit_how == "expert":
        return "engine"
    if exit_how == "stop_out":
        return "stop_out"
    if exit_how == "sl":
        risk = abs(entry - initial_stop)
        if exit_price is None or risk <= 0:
            return "stop"
        r = price_r(direction, entry, risk, exit_price)
        if r <= -0.5:
            return "stop"
        if r < 0.25:
            return "breakeven"
        return "trailing_stop"
    return "other" if exit_how else "unknown"


def bars_request(opened_at: datetime, now: datetime) -> tuple[Timeframe, int]:
    """The finest timeframe whose last MAX_BARS bars still reach back to the
    open, and how many to ask for. A few spare bars cover clock rounding."""
    minutes = max((now - opened_at).total_seconds() / 60, 1)
    for tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15):
        count = int(minutes / _TF_MINUTES[tf]) + 10
        if count <= MAX_BARS:
            return tf, count
    return Timeframe.M15, MAX_BARS


def bars_during(bars: list[Candle], timeframe: Timeframe, opened_at: datetime,
                closed_at: datetime) -> list[Candle]:
    """Bars that lie wholly inside the trade - opened at or after the fill and
    closed by the exit (a bar's time is its open). See the module docstring for
    why the straddling ones are left out."""
    span = timedelta(minutes=_TF_MINUTES.get(timeframe, 1))
    return [b for b in bars if b.time >= opened_at and b.time + span <= closed_at]


def excursions(direction, entry: float, initial_stop: float, bars: list[Candle],
               exit_price: float | None = None) -> tuple[float | None, float | None]:
    """(max favorable, max adverse) excursion in R, or (None, None) when there is
    nothing to measure. The exit fill counts as a price the trade reached, so a
    trade shorter than one whole bar still gets an honest lower bound."""
    risk = abs(entry - initial_stop)
    if risk <= 0 or entry <= 0 or (not bars and exit_price is None):
        return None, None
    highs = [b.high for b in bars] + ([exit_price] if exit_price is not None else [])
    lows = [b.low for b in bars] + ([exit_price] if exit_price is not None else [])
    best, worst = (max(highs), min(lows)) if _is_long(direction) else (min(lows), max(highs))
    return (round(max(0.0, price_r(direction, entry, risk, best)), 3),
            round(min(0.0, price_r(direction, entry, risk, worst)), 3))


def describe(autopsy: dict) -> str | None:
    """One short phrase for the trade-closed alert, e.g. 'full stop, best was +0.6R'."""
    label = EXIT_LABELS.get(autopsy.get("exit_reason") or "")
    if label is None:
        return None
    best = autopsy.get("max_favorable_r")
    if autopsy.get("exit_reason") in ("stop", "breakeven", "trailing_stop") and best is not None:
        return f"{label}, best was {best:+.1f}R"
    return label
