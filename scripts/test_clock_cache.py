r"""A restart while the market is shut must not blind the engine.

    .venv\Scripts\python.exe scripts\test_clock_cache.py

The offset used to live in memory only, which made the engine's weekend
behaviour depend on something arbitrary: whether it happened to restart. Seen on
2026-09-12 - the demo engine ran normally straight through Friday's close on its
cached offset, refreshing candles and evaluating until 00:54 Saturday, then a
restart left it with nothing to measure from and it stood down for the rest of
the weekend. Same market, same code, two different engines.

So the offset is persisted, and a value read back from disk is PROVISIONAL: good
enough to timestamp data with, not good enough to open a position on. That
distinction is the safety property, because the one way a cached offset goes
wrong is a DST transition - and those land on a Sunday, while the market is shut
and the cache is exactly what is in use.

Walks the real weekend: measure on Friday, restart on Saturday, open on Sunday -
including the DST case, where the confirming tick disagrees with the cache.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A fake MetaTrader5 whose ticking can be switched on and off, installed before
# mt5_time imports it.
fake_mt5 = types.ModuleType("MetaTrader5")
MARKET = {"open": True, "server_offset_hours": 3, "counter": 0}


def _symbol_info_tick(symbol):
    if not MARKET["open"]:
        # A shut market still returns the LAST tick - frozen. This is precisely
        # what the old code mistook for a live reading.
        return types.SimpleNamespace(time=int(1_000_000), time_msc=1_000_000_000)
    MARKET["counter"] += 1
    now = datetime.now(timezone.utc).timestamp() + MARKET["server_offset_hours"] * 3600
    return types.SimpleNamespace(time=int(now), time_msc=int(now * 1000) + MARKET["counter"])


fake_mt5.symbol_info_tick = _symbol_info_tick
sys.modules["MetaTrader5"] = fake_mt5

from engine.plugins.brokers import mt5_time                      # noqa: E402
from engine.plugins.brokers.mt5_time import (                    # noqa: E402
    ServerClock, ServerTimeUnavailable,
)

mt5_time.FRESHNESS_PROBE_SECONDS = 0.01      # keep the suite quick
WORK = Path(mkdtemp(prefix="clock-cache-"))


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def offset_or_none(clock: ServerClock):
    try:
        return clock.offset() / 3600
    except ServerTimeUnavailable:
        return "REFUSED"


def main() -> int:
    passed = []
    cache = WORK / "clock-icmarkets-demo.json"

    print("Friday, market open - the engine measures and remembers")
    MARKET.update(open=True, server_offset_hours=3)
    friday = ServerClock("EURUSD", cache_path=cache)
    passed.append(check("offset measured", offset_or_none(friday), 3.0))
    passed.append(check("not provisional - a live tick produced it", friday.is_provisional, False))
    passed.append(check("written to disk", cache.exists(), True))

    print("\nSaturday, market shut - a RESTART (this is the bug that was fixed)")
    MARKET["open"] = False
    saturday = ServerClock("EURUSD", cache_path=cache)
    passed.append(check("still knows the offset", offset_or_none(saturday), 3.0))
    passed.append(check("but flags it as provisional", saturday.is_provisional, True))

    print("\n  ...and with no cache at all it still refuses rather than guesses")
    blind = ServerClock("EURUSD", cache_path=WORK / "nonexistent.json")
    passed.append(check("refuses", offset_or_none(blind), "REFUSED"))

    print("\nSunday open, offset unchanged - the tick confirms it")
    MARKET["open"] = True
    saturday._attempted_at = 0.0                  # the 60s retry throttle has elapsed
    passed.append(check("offset unchanged", offset_or_none(saturday), 3.0))
    passed.append(check("no longer provisional", saturday.is_provisional, False))

    print("\nSunday open after a DST change - the tick CORRECTS the cache")
    MARKET.update(open=False)
    dst = ServerClock("EURUSD", cache_path=cache)
    passed.append(check("starts on the remembered +3h", offset_or_none(dst), 3.0))
    passed.append(check("provisional, so no entry is allowed yet", dst.is_provisional, True))
    MARKET.update(open=True, server_offset_hours=2)      # clocks went back
    dst._attempted_at = 0.0
    passed.append(check("corrected by the live tick", offset_or_none(dst), 2.0))
    passed.append(check("and confirmed", dst.is_provisional, False))

    print("\na stale cache is history, not evidence")
    stale = WORK / "stale.json"
    stale.write_text(json.dumps({
        "offset_seconds": 10800,
        "measured_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
    }), encoding="utf-8")
    MARKET["open"] = False
    passed.append(check("30-day-old cache ignored",
                        offset_or_none(ServerClock("EURUSD", cache_path=stale)), "REFUSED"))

    print("\na corrupt cache does not crash the engine")
    bad = WORK / "bad.json"
    bad.write_text("{not json at all", encoding="utf-8")
    passed.append(check("falls back to refusing",
                        offset_or_none(ServerClock("EURUSD", cache_path=bad)), "REFUSED"))

    print("\nan implausible cached offset is rejected")
    silly = WORK / "silly.json"
    silly.write_text(json.dumps({
        "offset_seconds": 31 * 3600,              # the 2026-09-06 drift, from disk
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")
    passed.append(check("31h offset refused",
                        offset_or_none(ServerClock("EURUSD", cache_path=silly)), "REFUSED"))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
