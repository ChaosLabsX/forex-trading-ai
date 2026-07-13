from __future__ import annotations

import time as time_module
from datetime import datetime, timezone

import MetaTrader5 as mt5


def measure_server_utc_offset_seconds(reference_symbol: str = "EURUSD") -> float:
    """MT5 timestamps (ticks, candles, deals) are in the broker's server time,
    not UTC - confirmed on this account: IC Markets runs ~3 hours ahead of UTC
    (EEST). Measuring this at runtime, rather than hardcoding a fixed offset,
    survives DST transitions without a code change."""
    tick = mt5.symbol_info_tick(reference_symbol)
    if tick is None or tick.time == 0:
        return 0.0
    return tick.time - time_module.time()


def server_epoch_to_utc(epoch_seconds: float, offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds - offset_seconds, tz=timezone.utc)
