"""What trending, cheap-to-trade instruments does this account offer?

The 48-test run says momentum works on gold and fails on all 15 FX pairs. That
suggests a mechanism - assets that TREND (commodities, indices) vs relative
prices between similar economies that MEAN-REVERT (FX majors) - which predicts
momentum should also work on silver, oil and indices. Never-examined data, so a
genuine out-of-sample test rather than more curve-fitting.

Two-phase on purpose: this account exposes ~3300 symbols (mostly stock CFDs),
and fetching candles for all of them takes ~10 million bars. So group first,
probe second - and only the handful of groups that could plausibly carry a
trend.

    python scripts/list_symbols.py            # show the groups
    python scripts/list_symbols.py Metals     # probe one group
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.models import Timeframe
from engine.indicators import atr
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider

COMMISSION_PER_LOT_ROUNDTURN = 7.0
# Gold costs ~0.017R, which is the entire reason an edge shows there at all.
# Anything far above this is answered before testing starts.
INTERESTING_COST_R = 0.05
ATR_PROBE_BARS = 300  # ATR(14) needs nothing like 3000 bars

# Stocks are excluded deliberately: thousands of them, they only trade during
# one exchange's session, and single-name risk is a different game entirely.
SKIP_GROUP_WORDS = ("stock", "share", "equit")


def top_group(path: str) -> str:
    return path.split("\\")[0] if "\\" in path else (path.split("/")[0] if "/" in path else path)


def main() -> None:
    settings = Settings()
    broker = MT5BrokerAdapter(settings)
    broker.connect()
    md = MT5MarketDataProvider(settings)

    everything = mt5.symbols_get() or []
    groups: dict[str, list] = defaultdict(list)
    for s in everything:
        groups[top_group(s.path)].append(s)

    wanted = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if wanted is None:
        print(f"{len(everything)} symbols in {len(groups)} groups\n")
        print(f"{'group':<28} {'count':>6}")
        print("-" * 36)
        for name, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            skip = any(w in name.lower() for w in SKIP_GROUP_WORDS)
            print(f"{name:<28} {len(members):>6}{'   (stocks - skipped)' if skip else ''}")
        print("\nRe-run with a group name to probe it, e.g.:")
        for name in sorted(groups):
            if not any(w in name.lower() for w in SKIP_GROUP_WORDS) and "forex" not in name.lower():
                print(f"    python scripts/list_symbols.py {name.split()[0]}")
        broker.disconnect()
        return

    targets = [s for g, members in groups.items() if wanted in g.lower() for s in members]
    if not targets:
        print(f"no group matching '{wanted}'. Run with no arguments to list groups.")
        broker.disconnect()
        return

    print(f"probing {len(targets)} symbols in groups matching '{wanted}'\n")
    print(f"{'symbol':<14} {'digits':>6} {'ATR(H1)':>12} {'cost_R':>8} {'H1 bars':>9}  path")
    print("-" * 92)

    rows = []
    for s in targets:
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
            candles = md.get_candles(s.name, Timeframe.H1, ATR_PROBE_BARS)
            atr_value = atr(candles[:-1], 14) or 0.0
        except Exception:
            continue
        if not atr_value or len(candles) < 100:
            continue
        # Same maths the backtest uses: cost as a fraction of a 1-ATR stop.
        cost_r = COMMISSION_PER_LOT_ROUNDTURN / (atr_value * value_per_price)
        cost_r += (info.spread * info.point) / atr_value
        rows.append((cost_r, s.name, info.digits, atr_value, len(candles), s.path))

    rows.sort()
    for cost_r, name, digits, atr_value, bars, path in rows:
        flag = "  <- cheap enough to matter" if cost_r <= INTERESTING_COST_R else ""
        print(f"{name:<14} {digits:>6} {atr_value:>12.5f} {cost_r:>8.4f} {bars:>9}  {path}{flag}")

    print(f"\n{len(rows)} probed. Symbols at or below {INTERESTING_COST_R}R are the only ones")
    print("where a small edge could survive its own costs.")
    broker.disconnect()


if __name__ == "__main__":
    main()
