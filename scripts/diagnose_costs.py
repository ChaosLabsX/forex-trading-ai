"""Why does the backtest think a trade costs more than 1R?

The backtest's net results are only as good as resolve_costs(), and its output
says costs run 1.2R+ per trade - impossible for a ~10 pip stop on EURUSD, which
should cost roughly 0.05R. Rather than guess which input is wrong, this prints
every number that feeds the calculation, per symbol, next to a sane reference.

    python scripts/diagnose_costs.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings
from engine.core.models import Timeframe
from engine.indicators import atr
from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider
from engine.plugins.strategies._common import UNIVERSE

COMMISSION_PER_LOT_ROUNDTURN = 7.0


def main() -> None:
    settings = Settings()
    broker = MT5BrokerAdapter(settings)
    broker.connect()
    md = MT5MarketDataProvider(settings)

    account = mt5.account_info()
    if account is not None:
        print(f"account currency: {account.currency}   server: {account.server}   "
              f"leverage: 1:{account.leverage}")
    print()
    print(f"{'symbol':<8} {'sel':<4} {'dig':<4} {'point':<9} {'spread_pts':>10} "
          f"{'spread_px':>10} {'tick_size':>10} {'tick_val':>9} {'val/px/lot':>11} "
          f"{'ATR(H1)':>9} {'spread_R':>9} {'comm_R':>8} {'cost_R':>8}")
    print("-" * 130)

    for symbol in UNIVERSE:
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"{symbol:<8} symbol_info() returned None")
            continue

        selected = info.select
        # Dynamic fields (spread, tick value) are only trustworthy once a symbol
        # is selected in Market Watch. If this flips a value, that IS the bug.
        if not selected:
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)

        tick_size = info.trade_tick_size or info.point
        value_per_price = (info.trade_tick_value / tick_size) if tick_size else 0.0
        spread_px = info.spread * info.point

        try:
            candles = md.get_candles(symbol, Timeframe.H1, 200)
            atr_value = atr(candles[:-1], 14) or 0.0
        except Exception:
            atr_value = 0.0

        spread_r = (spread_px / atr_value) if atr_value else float("nan")
        comm_r = (
            COMMISSION_PER_LOT_ROUNDTURN / (atr_value * value_per_price)
            if atr_value and value_per_price
            else float("nan")
        )
        print(
            f"{symbol:<8} {str(bool(selected))[:4]:<4} {info.digits:<4} {info.point:<9.6f} "
            f"{info.spread:>10} {spread_px:>10.6f} {tick_size:>10.6f} "
            f"{info.trade_tick_value:>9.4f} {value_per_price:>11.1f} {atr_value:>9.6f} "
            f"{spread_r:>9.3f} {comm_r:>8.3f} {spread_r + comm_r:>8.3f}"
        )

    print()
    print("Reference: a 1R stop of ~10 pips on EURUSD should cost ~0.05R round-trip.")
    print("cost_R above 0.5 means the cost model is wrong, not that the strategy is bad.")
    print()
    tick = mt5.symbol_info_tick("EURUSD")
    if tick is not None:
        age = datetime.now(timezone.utc).timestamp() - tick.time
        print(f"EURUSD last tick {age/60:.1f} min old  bid={tick.bid} ask={tick.ask} "
              f"live_spread_px={tick.ask - tick.bid:.6f}")
        print("A stale tick / huge live spread means the market is shut or in rollover -")
        print("in which case a spread SNAPSHOT is a terrible proxy for historical cost.")

    broker.disconnect()


if __name__ == "__main__":
    main()
