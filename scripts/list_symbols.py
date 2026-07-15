"""What non-FX instruments does this account actually offer?

The 48-test run says momentum works on gold and fails on every FX pair. That
suggests a mechanism - trending assets (commodities, indices) vs mean-reverting
relative prices (FX majors) - which predicts momentum should ALSO work on
silver, oil and indices. Those are data we have never looked at, so they are a
genuine out-of-sample test rather than more curve-fitting.

This prints the tradeable non-FX symbols with the two things that decide whether
they can be tested: whether costs are cheap enough to leave an edge alive, and
whether the broker has enough history.

    python scripts/list_symbols.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.models import Timeframe
from engine.indicators import atr
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider

COMMISSION_PER_LOT_ROUNDTURN = 7.0
# Gold's cost is ~0.017R, which is why an edge survives there at all. Anything
# far above this is a symbol where costs eat the premise before it starts.
INTERESTING_COST_R = 0.05


def main() -> None:
    settings = Settings()
    broker = MT5BrokerAdapter(settings)
    broker.connect()
    md = MT5MarketDataProvider(settings)

    everything = mt5.symbols_get()
    if everything is None:
        print("symbols_get() returned None")
        return

    # FX majors/crosses are exactly what the data says momentum fails on, so
    # skip them: 6-letter names made of currency codes.
    codes = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}

    def is_fx(name: str) -> bool:
        return len(name) == 6 and name[:3] in codes and name[3:] in codes

    candidates = [s for s in everything if not is_fx(s.name)]
    print(f"{len(everything)} symbols total, {len(candidates)} non-FX\n")
    print(f"{'symbol':<14} {'digits':>6} {'ATR(H1)':>12} {'cost_R':>8} {'H1 bars':>9}  path")
    print("-" * 92)

    rows = []
    for s in candidates:
        if not s.select:
            mt5.symbol_select(s.name, True)
        info = mt5.symbol_info(s.name)
        if info is None or not info.trade_tick_value:
            continue
        tick_size = info.trade_tick_size or info.point
        if not tick_size:
            continue
        value_per_price = info.trade_tick_value / tick_size
        try:
            candles = md.get_candles(s.name, Timeframe.H1, 3000)
            bars = len(candles)
            atr_value = atr(candles[:-1], 14) or 0.0
        except Exception:
            continue
        if not atr_value or bars < 500:
            continue
        # Same maths the backtest uses: commission as a fraction of a 1-ATR stop.
        cost_r = COMMISSION_PER_LOT_ROUNDTURN / (atr_value * value_per_price)
        cost_r += (info.spread * info.point) / atr_value
        rows.append((cost_r, s.name, info.digits, atr_value, bars, s.path))

    rows.sort()
    for cost_r, name, digits, atr_value, bars, path in rows:
        flag = "  <- cheap enough to matter" if cost_r <= INTERESTING_COST_R else ""
        print(f"{name:<14} {digits:>6} {atr_value:>12.5f} {cost_r:>8.4f} {bars:>9}  {path}{flag}")

    print()
    print(f"Symbols at or below {INTERESTING_COST_R}R cost are the only ones where a small edge")
    print("could survive. Everything else is answered before we start.")
    broker.disconnect()


if __name__ == "__main__":
    main()
