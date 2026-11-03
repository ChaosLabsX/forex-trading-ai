r"""Was the broker's UTC offset the same in summer as it is now? Read-only.

    .venv\Scripts\python.exe scripts\diagnose_clock_history.py

Every bar time the engine and the backtest use is MT5 server time converted to
UTC with ONE offset - the one measured now. That is right for recent bars, and
wrong by an hour for any bar from before a summer/winter switch, if the
broker's server time switches. Whether it does is answered here from the
broker's own records: for one demo trade per week, the entry deal's server
timestamp minus the moment the engine recorded the trade (true UTC, from the
VPS clock) IS the broker's offset at that time.

It also prints GBPJPY's minute bars around the 2026-10-13 09:00 London open in
true UTC. Three trades took that setup; the two demo ones moved their stops to
entry, the live one hit its full stop - this shows what the price actually did
after the fills.

Attaches to the demo terminal the way scripts/backtest.py does (no login, no
order, nothing written), so the engines can keep running.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.config import Settings                     # noqa: E402
from engine.supabase_client import SupabaseClient     # noqa: E402

UTC = timezone.utc
LONDON_OPEN = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")  # the demo account and terminal
    import MetaTrader5 as mt5
    from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter
    from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider

    broker = MT5BrokerAdapter(settings)
    broker.connect()
    market_data = MT5MarketDataProvider(settings)
    supabase = SupabaseClient(settings)
    try:
        print(f"broker UTC offset now, as measured: {market_data._offset() / 3600:+.2f}h\n")

        trades = supabase.select("trades", {
            "account_key": f"eq.{settings.account_key}",
            "select": "mt5_ticket,symbol,opened_at",
            "order": "opened_at.asc",
            "limit": "5000",
        })
        first_per_week: dict[str, dict] = {}
        for t in trades:
            week = datetime.fromisoformat(t["opened_at"]).strftime("%G-W%V")
            first_per_week.setdefault(week, t)

        print("broker UTC offset when each week's first trade opened")
        print("(entry deal's server time minus the time the engine recorded the trade):")
        for week, t in sorted(first_per_week.items()):
            deals = mt5.history_deals_get(position=int(t["mt5_ticket"])) or ()
            entry = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
            if not entry:
                print(f"  {week}  {t['opened_at'][:16]}  {t['symbol']:7s}  (no entry deal in history)")
                continue
            recorded = datetime.fromisoformat(t["opened_at"]).timestamp()
            hours = (entry[0].time - recorded) / 3600
            print(f"  {week}  {t['opened_at'][:16]} UTC  {t['symbol']:7s}  offset {hours:+.2f}h")

        print("\nthe three GBPJPY trades on 2026-10-13:")
        rows = supabase.select("trades", {
            "symbol": "eq.GBPJPY",
            "and": "(opened_at.gte.2026-10-13T08:59:00,opened_at.lt.2026-10-13T09:03:00)",
            "select": "account_key,strategy_name,mt5_ticket,direction,entry_price,initial_stop_loss,stop_loss,"
                      "exit_price,exit_reason,opened_at,closed_at",
            "order": "opened_at.asc",
        })
        then_offset = None
        for r in rows:
            print(f"  {r['account_key'][-4:]} {r['strategy_name']:24s} {r['direction']} entry {r['entry_price']} "
                  f"stop {r['initial_stop_loss']:.3f} (last {r['stop_loss']:.3f}) exit {r['exit_price']} "
                  f"{r['exit_reason']} | opened {r['opened_at'][11:19]} closed {r['closed_at'][11:19]}")
            if then_offset is None and r["account_key"] == settings.account_key:
                deals = mt5.history_deals_get(position=int(r["mt5_ticket"])) or ()
                entry = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
                if entry:
                    then_offset = entry[0].time - datetime.fromisoformat(r["opened_at"]).timestamp()
        if then_offset is None:
            print("  (no demo GBPJPY trade with an entry deal - cannot place the bars)")
            return 1
        then_offset = round(then_offset / 900) * 900  # offsets land on quarter-hours
        print(f"  broker UTC offset that morning: {then_offset / 3600:+.2f}h")

        minutes_back = int((datetime.now(UTC) - LONDON_OPEN).total_seconds() / 60) + 30
        rates = mt5.copy_rates_from_pos("GBPJPY", mt5.TIMEFRAME_M1, 0, minutes_back)
        if rates is None or len(rates) == 0:
            print(f"\nno GBPJPY minute bars returned ({mt5.last_error()})")
            return 1
        print("\nGBPJPY 1-minute bars, true UTC (bid prices):")
        start, end = LONDON_OPEN - timedelta(minutes=2), LONDON_OPEN + timedelta(minutes=12)
        shown = 0
        for bar in rates:
            t = datetime.fromtimestamp(int(bar["time"]) - then_offset, tz=UTC)
            if start <= t <= end:
                shown += 1
                print(f"  {t:%H:%M}  open {bar['open']:.3f}  high {bar['high']:.3f}  "
                      f"low {bar['low']:.3f}  close {bar['close']:.3f}")
        if not shown:
            first = datetime.fromtimestamp(int(rates[0]["time"]) - then_offset, tz=UTC)
            print(f"  none in the window - the oldest minute bar returned is {first:%Y-%m-%d %H:%M} UTC")
    finally:
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
