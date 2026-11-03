r"""Historical bars get the UTC offset that applied when they formed.

    .venv\Scripts\python.exe scripts\test_clock_history.py

This broker's server runs on New York close: UTC+3 while New York is on daylight
time, UTC+2 otherwise - read off its own deal records on 2026-11-03
(scripts/diagnose_clock_history.py). Converting all history with the ONE offset
measured now labelled every summer bar an hour late in a winter backtest: the
London session ran an hour off for two thirds of each year, and the trade
autopsy measured the hour BEFORE each trade (a 13-Oct GBPJPY short read "+3.1R
best" when it never reached +1R).

Covers the rule (US daylight-saving dates, the broker's measured history), the
provider's get_history against get_candles on bars that straddle a switch, the
refusal when the rule and the measured clock disagree, the real 13-Oct GBPJPY
bars, and that the backtest, the engine's autopsy and the backfill all read
history through it.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import trade_autopsy                                                    # noqa: E402
from engine.core.interfaces.market_data import MarketDataUnavailable               # noqa: E402
from engine.core.models import Direction, Timeframe                                # noqa: E402
from engine.plugins.brokers import mt5_time                                        # noqa: E402
from engine.plugins.market_data import mt5_market_data                             # noqa: E402

UTC = timezone.utc
H = 3600


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def server_epoch(true_utc: datetime, offset_hours: int) -> int:
    return int(true_utc.timestamp()) + offset_hours * H


def provider(measured_offset_seconds: float, rows):
    """An MT5MarketDataProvider with its clock and MT5's rates replaced."""
    p = mt5_market_data.MT5MarketDataProvider.__new__(mt5_market_data.MT5MarketDataProvider)
    p._settings = None
    p._clock = types.SimpleNamespace(offset=lambda: measured_offset_seconds)
    mt5_market_data.mt5.copy_rates_from_pos = lambda symbol, tf, start, count: rows
    return p


def row(server_time: int, o, h, low, c):
    return {"time": server_time, "open": o, "high": h, "low": low, "close": c, "tick_volume": 1}


def main() -> int:
    passed = []
    rule = mt5_time.ny_close_offset_seconds

    print("the US daylight-saving dates the broker follows")
    switches = {2023: ("03-12", "11-05"), 2024: ("03-10", "11-03"), 2025: ("03-09", "11-02"),
                2026: ("03-08", "11-01"), 2027: ("03-14", "11-07")}
    ok = True
    for year, (spring, autumn) in switches.items():
        start, end = at(f"{year}-{spring}T07:00"), at(f"{year}-{autumn}T06:00")
        ok &= rule(start - timedelta(minutes=1)) == 2 * H and rule(start) == 3 * H
        ok &= rule(end - timedelta(minutes=1)) == 3 * H and rule(end) == 2 * H
    passed.append(check("UTC+3 from the 2nd Sunday of March 07:00 UTC to the 1st Sunday of November 06:00 UTC, 2023-2027",
                        ok, True))

    print("\nthe broker's own record (first trade of each week, 2026-11-03 diagnostic)")
    measured = {"2026-07-16T17:33": 3, "2026-07-20T01:01": 3, "2026-07-27T08:00": 3, "2026-08-03T08:00": 3,
                "2026-08-10T08:00": 3, "2026-08-17T08:00": 3, "2026-08-24T08:00": 3, "2026-08-31T02:00": 3,
                "2026-09-07T08:00": 3, "2026-09-14T09:00": 3, "2026-09-21T08:00": 3, "2026-09-28T08:00": 3,
                "2026-10-05T08:00": 3, "2026-10-12T08:01": 3, "2026-10-19T08:00": 3, "2026-10-26T08:00": 3,
                "2026-11-02T09:00": 2}
    passed.append(check("the rule reproduces all 17 measured weeks (incl. +3 on 26 Oct, after Europe switched)",
                        {k: rule(at(k)) // H for k in measured}, measured))

    print("\nserver time back to true UTC")
    passed.append(check("13 Oct 12:00 server (summer) -> 09:00 UTC",
                        mt5_time.server_epoch_to_utc_ny_close(server_epoch(at("2026-10-13T09:00"), 3)), at("2026-10-13T09:00")))
    passed.append(check("2 Nov 11:00 server (winter) -> 09:00 UTC",
                        mt5_time.server_epoch_to_utc_ny_close(server_epoch(at("2026-11-02T09:00"), 2)), at("2026-11-02T09:00")))
    bad = []
    t = at("2025-01-01T00:00")
    while t < at("2026-01-01T00:00"):
        back = mt5_time.server_epoch_to_utc_ny_close(server_epoch(t, rule(t) // H))
        if back != t:
            bad.append(t)
        t += timedelta(hours=1)
    # The one exception: when clocks fall back, server 08:00-09:00 happens twice,
    # so that hour cannot be told apart. It is Sunday 01:00 in New York - FX is
    # shut, no bar exists then.
    passed.append(check("every hour of 2025 survives the round trip, except the repeated fall-back hour",
                        bad, [at("2025-11-02T06:00")]))
    passed.append(check("...which is a Sunday, hours before the FX week opens (Sunday 22:00 UTC)",
                        bad[0].strftime("%A") if bad else None, "Sunday"))

    print("\nthe rule is trusted only when the clock measured now agrees")
    now = datetime.now(UTC)
    passed.append(check("measured offset == the rule's for now -> trusted", mt5_time.follows_ny_close(rule(now), now), True))
    other = 5 * H - rule(now)  # the other season's offset
    passed.append(check("an hour off -> not trusted", mt5_time.follows_ny_close(other, now), False))

    print("\nget_history vs get_candles on bars either side of the 1 Nov switch")
    real_copy = mt5_market_data.mt5.copy_rates_from_pos
    try:
        rows = [row(server_epoch(at("2026-10-13T09:00"), 3), 1, 1, 1, 1),
                row(server_epoch(at("2026-11-02T09:00"), 2), 1, 1, 1, 1)]
        p = provider(rule(now), rows)
        passed.append(check("history: both bars at their true 09:00 UTC",
                            [c.time for c in p.get_history("GBPJPY", Timeframe.H1, 2)],
                            [at("2026-10-13T09:00"), at("2026-11-02T09:00")]))
        p = provider(2 * H, rows)
        passed.append(check("one offset (+2h, today's): the summer bar lands at 10:00 - the bug",
                            [c.time.strftime("%m-%d %H:%M") for c in p.get_candles("GBPJPY", Timeframe.H1, 2)],
                            ["10-13 10:00", "11-02 09:00"]))
        p = provider(other, rows)
        try:
            p.get_history("GBPJPY", Timeframe.H1, 2)
            refused = None
        except mt5_market_data.HistoryClockMismatch as exc:
            refused = exc
        passed.append(check("rule and measured clock disagree -> refused, not guessed",
                            isinstance(refused, MarketDataUnavailable), True))

        print("\nthe 13-Oct GBPJPY short, on the real minute bars (bid)")
        real = [("09:00", 208.942, 209.100, 208.942, 209.100), ("09:01", 209.100, 209.125, 209.090, 209.115),
                ("09:02", 209.115, 209.124, 209.068, 209.071), ("09:03", 209.071, 209.106, 209.059, 209.069),
                ("09:04", 209.069, 209.084, 209.026, 209.056), ("09:05", 209.049, 209.079, 209.046, 209.078),
                ("09:06", 209.078, 209.100, 209.056, 209.082), ("09:07", 209.083, 209.088, 209.053, 209.053),
                ("09:08", 209.053, 209.114, 209.053, 209.114), ("09:09", 209.121, 209.142, 209.108, 209.130)]
        rows = [row(server_epoch(at(f"2026-10-13T{hm}"), 3), *ohlc) for hm, *ohlc in real]
        bars = provider(rule(now), rows).get_history("GBPJPY", Timeframe.M1, len(rows))
        inside = trade_autopsy.bars_during(bars, Timeframe.M1, at("2026-10-13T09:00:50"), at("2026-10-13T09:09:30"))
        best, worst = trade_autopsy.excursions(Direction.SHORT, 209.084, 209.14541, inside, 209.145)
        passed.append(check("best +0.94R - under the +1R that moves the stop, so the live engine was right not to",
                            (round(best, 2), round(worst, 2)), (0.94, -0.99)))
        passed.append(check("the alert would say so", trade_autopsy.describe(
            {"exit_reason": "stop", "max_favorable_r": best}), "full stop, best was +0.9R"))
        old = provider(2 * H, rows).get_candles("GBPJPY", Timeframe.M1, len(rows))
        passed.append(check("with today's single offset those same bars sit an hour later - outside the trade",
                            trade_autopsy.bars_during(old, Timeframe.M1, at("2026-10-13T09:00:50"), at("2026-10-13T09:09:30")),
                            []))
    finally:
        mt5_market_data.mt5.copy_rates_from_pos = real_copy

    print("\nevery reader of long history goes through get_history")
    src = lambda rel: (ROOT / rel).read_text(encoding="utf-8")  # noqa: E731
    passed.append(check("the backtest", ("md.get_history(" in src("scripts/backtest.py"),
                                         "md.get_candles(" in src("scripts/backtest.py")), (True, False)))
    passed.append(check("the engine's trade autopsy", "market_data.get_history(" in src("engine/loop.py"), True))
    passed.append(check("the backfill, bars and deal times alike",
                        ("market_data.get_history(" in src("scripts/backfill_trade_autopsy.py"),
                         "server_epoch_to_utc_ny_close)" in src("scripts/backfill_trade_autopsy.py")), (True, True)))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
