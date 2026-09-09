"""The broker's clock, measured rather than assumed - and never guessed.

MT5 reports every timestamp - ticks, candles, deals - in the broker's server
time, not UTC. IC Markets runs ~3h ahead. That offset is measured at runtime
rather than hardcoded so DST transitions need no code change.

WHY THIS IS MORE THAN ONE SUBTRACTION. The measurement is `last tick - now`,
which is the offset only if that tick is CURRENT. Start the engine while the
market is closed and the last tick is hours old, so the reading is the offset
minus that staleness - and cached for the process lifetime, it stays wrong
until the next restart.

That happened. On Sunday 2026-09-06 the demo engine measured against a
31-hour-old tick and then spent three days stamping bars ~18 hours into the
future: it wrote future-dated rows into the candles table, and it silently
moved london_breakout_v1's 07:00-11:00 UTC window to 01:00-05:00, so the lab
spent those days trading the Asian session while labelling it the London open.
Nothing errored. Every log line looked ordinary.

Two defences follow from that:

  * establish freshness FIRST, by watching the tick actually move. A live
    EURUSD ticks many times a second; a tick time that does not advance means
    the market is shut, not that it is quiet.
  * never fall back to zero. The old code returned 0.0 when it could not
    measure, which is not "no offset" - it is a three-hour error on this
    broker, applied silently to every timestamp.
"""

from __future__ import annotations

import logging
import time as time_module
from datetime import datetime, timezone

import MetaTrader5 as mt5

from engine.core.interfaces.market_data import MarketDataUnavailable

logger = logging.getLogger("engine.mt5_time")

# No broker sits further than this from UTC. A reading beyond it is not a
# timezone, it is a stale tick being mistaken for one.
MAX_PLAUSIBLE_OFFSET_SECONDS = 14 * 3600
# Real offsets land on whole hours, or quarter-hours at the exotic end (Nepal
# is UTC+5:45). Snapping to that grid removes the sub-minute jitter of
# measuring against a tick that is always a moment old - which is why bars used
# to land at :00:10 past the hour rather than on it.
OFFSET_QUANTUM_SECONDS = 900
# Gap between the two freshness samples.
FRESHNESS_PROBE_SECONDS = 1.5
# Re-measure this often, so a DST transition is picked up without a restart.
REFRESH_SECONDS = 6 * 3600
# ...but retry this often while no offset is known at all, so a Monday open is
# picked up promptly without probing on every single call.
RETRY_SECONDS = 60


class ServerTimeUnavailable(MarketDataUnavailable):
    """The broker's UTC offset cannot be measured and none is cached.

    Provider-wide by inheritance: it affects every symbol equally, so the loop
    stops the cycle on it rather than raising the same thing once per symbol.
    """


def _tick_stamp(tick) -> int | None:
    """A comparable instant for a tick, in milliseconds, or None if there isn't one."""
    if tick is None or tick.time == 0:
        return None
    # time_msc separates ticks inside the same second; .time alone can look
    # frozen through a quiet second on a perfectly live market.
    return getattr(tick, "time_msc", 0) or tick.time * 1000


def measure_server_utc_offset_seconds(reference_symbol: str = "EURUSD") -> float | None:
    """Server clock minus UTC, in seconds - or None if it cannot be trusted now.

    None means "the market is not ticking", which is a normal weekend state and
    not an error. It is emphatically not zero.
    """
    first = _tick_stamp(mt5.symbol_info_tick(reference_symbol))
    if first is None:
        return None

    time_module.sleep(FRESHNESS_PROBE_SECONDS)
    tick = mt5.symbol_info_tick(reference_symbol)
    second = _tick_stamp(tick)
    if second is None or second == first:
        return None  # not ticking: market closed, or the symbol is unsubscribed

    raw = tick.time - time_module.time()
    if abs(raw) > MAX_PLAUSIBLE_OFFSET_SECONDS:
        # The tick moved but the reading is impossible - a terminal mid-sync,
        # or a machine clock far out. Refuse rather than adopt it.
        logger.warning("implausible server offset %.0fs from %s - ignoring", raw, reference_symbol)
        return None
    return round(raw / OFFSET_QUANTUM_SECONDS) * OFFSET_QUANTUM_SECONDS


def server_epoch_to_utc(epoch_seconds: float, offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds - offset_seconds, tz=timezone.utc)


class ServerClock:
    """A measured, self-refreshing view of the broker's clock.

    Shared by the broker adapter and the market-data provider because both need
    identical behaviour, and two copies of this would drift apart exactly when
    it mattered. Keeping the last good offset across a failed re-measure is
    deliberate: an offset cannot change while the market is closed, which is
    the only time measurement fails.
    """

    def __init__(self, reference_symbol: str = "EURUSD") -> None:
        self._reference_symbol = reference_symbol
        self._offset: float | None = None
        self._measured_at = 0.0
        self._attempted_at = 0.0
        self._warned = False

    def refresh(self, force: bool = False) -> float | None:
        """Re-measure if due. Returns the current offset, or None if never measured."""
        now = time_module.monotonic()
        if not force:
            if self._offset is not None:
                if now - self._measured_at < REFRESH_SECONDS:
                    return self._offset
            elif now - self._attempted_at < RETRY_SECONDS:
                return None

        self._attempted_at = now
        measured = measure_server_utc_offset_seconds(self._reference_symbol)
        if measured is None:
            if self._offset is None and not self._warned:
                logger.warning(
                    "broker UTC offset not measurable yet: %s is not ticking (market closed?). "
                    "Timestamps are on hold until it is.",
                    self._reference_symbol,
                )
                self._warned = True
            return self._offset

        if self._offset is None:
            logger.info("broker UTC offset measured: %+.2fh", measured / 3600)
        elif measured != self._offset:
            logger.warning(
                "broker UTC offset changed: %+.2fh -> %+.2fh (DST transition?)",
                self._offset / 3600, measured / 3600,
            )
        self._offset = measured
        self._measured_at = now
        self._warned = False
        return measured

    def offset(self) -> float:
        offset = self.refresh()
        if offset is None:
            raise ServerTimeUnavailable(
                f"the broker's UTC offset is unknown - {self._reference_symbol} is not ticking. "
                "Refusing to timestamp data from a guess."
            )
        return offset

    def to_utc(self, epoch_seconds: float) -> datetime:
        return server_epoch_to_utc(epoch_seconds, self.offset())

    def offset_if_known(self) -> float | None:
        return self._offset
