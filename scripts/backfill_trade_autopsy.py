r"""Fill in how past trades ended and how far they went (migration 0017).

Run ON THE VPS, once per account, with that account's engine STOPPED - it
attaches to the same MT5 terminal to read deal history and price bars:

    .venv\Scripts\python.exe scripts\backfill_trade_autopsy.py                          # demo: shows what it found
    .venv\Scripts\python.exe scripts\backfill_trade_autopsy.py --apply                  # demo: writes it
    .venv\Scripts\python.exe scripts\backfill_trade_autopsy.py --env-file .env.live --apply   # live

New trades get these fields from the engine as they close; this only covers
the ones that closed before. It uses the same code the engine uses
(engine/trade_autopsy.py, summarize_closed_deals), with the finest price bars
MT5 still holds for each trade: 1-minute for recent ones, 5- or 15-minute
further back - so older excursions are a little coarser.

Idempotent: only rows whose exit_reason is still NULL are touched, and a row
whose deals or bars can't be found is left NULL rather than guessed. One small
write per trade, once - well inside the free plan.

--recompute redoes EVERY closed trade of the account, overwriting what is
there. Needed once after 2026-10-19, when the excursions stopped counting the
partial minutes before the fill and after the exit (engine/trade_autopsy.py).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import trade_autopsy                                # noqa: E402
from engine.core.models import Timeframe                        # noqa: E402
from engine.supabase_client import SupabaseClient              # noqa: E402
from repair_entry_prices import engine_running, load_settings  # noqa: E402


def bars_covering(market_data, cache: dict, symbol: str, opened: datetime, now: datetime):
    """The finest bars MT5 still holds that reach back to `opened`, trying
    1-minute first and falling back to 5, 15 and 60. Cached per symbol: rows
    come oldest-first, so the first trade fetches enough for all the rest."""
    minutes = max((now - opened).total_seconds() / 60, 1)
    for timeframe, per in ((Timeframe.M1, 1), (Timeframe.M5, 5), (Timeframe.M15, 15), (Timeframe.H1, 60)):
        count = int(minutes / per) + 10
        if count > trade_autopsy.MAX_BARS:
            continue
        key = (symbol, timeframe)
        if key not in cache or cache[key][0] < count:  # [0] = how many were asked for
            try:
                cache[key] = (count, market_data.get_candles(symbol, timeframe, count))
            except Exception:
                cache[key] = (count, [])
        bars = cache[key][1]
        if bars and bars[0].time <= opened:
            return timeframe, bars
    return None, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", help="e.g. .env.live for the live account")
    parser.add_argument("--apply", action="store_true", help="write the results (default: show them)")
    parser.add_argument("--recompute", action="store_true",
                        help="redo every closed trade, not only those without an autopsy")
    args = parser.parse_args()

    settings = load_settings(args.env_file)
    account = settings.account_key
    supabase = SupabaseClient(settings)
    rows = supabase.select("trades", {
        "account_key": f"eq.{account}",
        "status": "eq.CLOSED",
        **({} if args.recompute else {"exit_reason": "is.null"}),
        "void_reason": "is.null",
        "select": "id,mt5_ticket,symbol,direction,entry_price,initial_stop_loss,stop_loss,opened_at,closed_at",
        "order": "opened_at.asc",
    })
    print(f"{account}: {len(rows)} closed trade(s) " + ("to recompute" if args.recompute else "without an autopsy"))
    if not rows:
        return 0

    pid = engine_running(account)
    if pid is not None:
        print(f"\nREFUSING: the {account} engine is running (pid {pid}) and this attaches to its "
              "MT5 terminal. Stop it first, run this, then start it again.")
        return 2

    import MetaTrader5 as mt5
    from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter, summarize_closed_deals
    from engine.plugins.market_data.mt5_market_data import MT5MarketDataProvider

    broker = MT5BrokerAdapter(settings)
    broker.connect()  # verifies the terminal is logged in to THIS account's server
    market_data = MT5MarketDataProvider(settings)
    now = datetime.now(timezone.utc)
    bars_cache: dict = {}
    found, missing, kinds = [], Counter(), Counter()
    try:
        for row in rows:
            ticket, symbol = row["mt5_ticket"], row["symbol"]
            breakdown = summarize_closed_deals(mt5.history_deals_get(position=int(ticket)), broker._to_utc)
            if breakdown is None:
                missing["no closing deal in MT5 history"] += 1
                continue
            entry = float(row["entry_price"])
            stop = float(row["initial_stop_loss"] or row["stop_loss"])
            update = {"exit_reason": trade_autopsy.classify_exit(
                row["direction"], entry, stop, breakdown.exit_price, breakdown.exit_how)}
            if breakdown.exit_price is not None:
                update["exit_price"] = breakdown.exit_price

            opened = datetime.fromisoformat(row["opened_at"])
            closed = breakdown.exit_time or datetime.fromisoformat(row["closed_at"])
            timeframe, bars = bars_covering(market_data, bars_cache, symbol, opened, now)
            if timeframe is not None:
                best, worst = trade_autopsy.excursions(
                    row["direction"], entry, stop, trade_autopsy.bars_during(bars, timeframe, opened, closed),
                    breakdown.exit_price)
                if best is not None:
                    update["max_favorable_r"], update["max_adverse_r"] = best, worst
            else:
                missing["price bars don't reach back that far (exit kept, excursions left empty)"] += 1

            kinds[update["exit_reason"]] += 1
            found.append((row, update, timeframe))
            note = trade_autopsy.describe(update) or update["exit_reason"]
            tf_text = timeframe.value if timeframe is not None else "-"
            print(f"  {row['opened_at'][:16]} {symbol:7s} {row['direction']:5s} {tf_text:3s} -> {note}")
    finally:
        broker.disconnect()

    print(f"\n{len(found)} trade(s) read: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    for why, n in missing.items():
        print(f"  {n} {why}")
    if not args.apply:
        print("\nNothing written. Re-run with --apply to save these.")
        return 0

    written = 0
    for row, update, _ in found:
        try:
            # Without --recompute, only where exit_reason is still NULL: never
            # overwrite what the engine wrote meanwhile.
            where = {"id": f"eq.{row['id']}"} if args.recompute else {"id": f"eq.{row['id']}", "exit_reason": "is.null"}
            supabase.update("trades", where, update)
            written += 1
        except Exception as exc:
            print(f"  write failed for {row['mt5_ticket']}: {exc}")
    print(f"\n{written} trade(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
