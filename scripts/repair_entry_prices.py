r"""Repair trades that were recorded with entry_price = 0.

Until 2026-09-16 place_order() recorded MT5's result.price as the entry. The
LIVE server returns 0.0 there (the demo returns the fill), so every live trade
was saved as opened at 0 with a risk_amount ~2,400x too large - which reads
every real stop-out as ~0R. See MT5BrokerAdapter._fill_price. The broker's own
SL/TP were correct throughout; only the record is wrong, and this fixes it.

Run ON THE VPS, with the engine for that account STOPPED - it attaches to the
same MT5 terminal to read the real fills from deal history:

    .venv\Scripts\python.exe scripts\repair_entry_prices.py --env-file .env.live           # shows the changes
    .venv\Scripts\python.exe scripts\repair_entry_prices.py --env-file .env.live --apply   # writes them

The entry comes from the broker's own entry deal. risk_amount is rebuilt from
the value the engine captured at open, not re-read from today's tick value:
risk_amount was |0 - stop| x value_per_lot x lots, so dividing by the stop
recovers value_per_lot x lots exactly as it was then. Today's tick value is only
used as a cross-check, and a row where the two disagree is left alone.

Idempotent: it only ever touches rows whose entry_price is still <= 0.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.config import Settings                              # noqa: E402
from engine.supabase_client import SupabaseClient              # noqa: E402

# Today's tick value vs the one captured at open. FX conversion rates drift a
# little in a week; more than this means the row is not what this script thinks.
CROSS_CHECK_TOLERANCE = 0.15


def repaired_risk(old_risk: float, stop: float, entry: float) -> float:
    """risk_amount as it should have been recorded, from the wrong one.

    old_risk = |0 - stop| x value x lots, so value x lots = old_risk / stop."""
    return old_risk / abs(stop) * abs(entry - stop)


def stop_on_losing_side(direction: str, entry: float, stop: float) -> bool:
    return stop < entry if direction == "LONG" else stop > entry


def engine_running(account_key: str) -> int | None:
    """The pid of a live engine process for this account, or None.

    Reads the pid file run_engine.py publishes. Stop-ScheduledTask kills the
    process without running atexit, so the file can outlive it - hence the
    liveness check. Never os.kill(pid, 0) on Windows: that TERMINATES the process."""
    pid_file = ROOT / "logs" / f"engine-{account_key}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        size = ctypes.c_ulong(1024)
        name = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            if "python" not in name.value.lower():
                return None  # the pid was recycled by something else
        return pid
    finally:
        kernel32.CloseHandle(handle)


def load_settings(env_file: str | None) -> Settings:
    if not env_file:
        return Settings()
    path = Path(env_file)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise SystemExit(f"--env-file '{path}' does not exist")
    base = ROOT / ".env"
    return Settings(_env_file=(str(base), str(path)) if base.exists() else (str(path),))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", help="e.g. .env.live for the live account")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: show them)")
    args = parser.parse_args()

    settings = load_settings(args.env_file)
    account = settings.account_key
    supabase = SupabaseClient(settings)

    rows = supabase.select("trades", {
        "account_key": f"eq.{account}",
        "entry_price": "lte.0",
        "select": "id,mt5_ticket,symbol,direction,lot_size,entry_price,stop_loss,"
                  "initial_stop_loss,risk_amount,realized_pnl,status",
        "order": "opened_at.asc",
    })
    print(f"{account}: {len(rows)} trade(s) recorded with entry_price <= 0")
    if not rows:
        return 0

    pid = engine_running(account)
    if pid is not None:
        print(f"\nREFUSING: the {account} engine is running (pid {pid}) and this attaches to its "
              "MT5 terminal. Stop it first, run this, then start it again.")
        return 2

    import MetaTrader5 as mt5
    from engine.plugins.brokers.mt5_broker import MT5BrokerAdapter

    broker = MT5BrokerAdapter(settings)
    broker.connect()  # verifies the terminal is logged in to THIS account's server
    fixes, problems = [], 0
    try:
        for row in rows:
            ticket, symbol = row["mt5_ticket"], row["symbol"]
            label = f"  {ticket} {symbol} {row['direction']} {row['lot_size']} lot"
            deals = mt5.history_deals_get(position=int(ticket)) or ()
            entries = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN and d.price > 0]
            if not entries:
                print(f"{label}: SKIPPED - no entry deal for this position in MT5 history")
                problems += 1
                continue
            volume = sum(d.volume for d in entries)
            entry = sum(d.price * d.volume for d in entries) / volume

            stop = row["initial_stop_loss"] or row["stop_loss"]
            if not stop or not stop_on_losing_side(row["direction"], entry, stop):
                print(f"{label}: SKIPPED - stop {stop} is not on the losing side of entry {entry}")
                problems += 1
                continue

            old_risk = row["risk_amount"]
            today = broker.get_price_value_per_lot(symbol)
            check = today * row["lot_size"] * abs(entry - stop) if today else None
            new_risk = repaired_risk(old_risk, stop, entry) if old_risk else check
            if new_risk is None or new_risk <= 0:
                print(f"{label}: SKIPPED - cannot rebuild risk_amount")
                problems += 1
                continue
            if check and abs(new_risk - check) / check > CROSS_CHECK_TOLERANCE:
                print(f"{label}: SKIPPED - rebuilt risk ${new_risk:.2f} disagrees with today's "
                      f"tick value (${check:.2f}) by more than {CROSS_CHECK_TOLERANCE:.0%}")
                problems += 1
                continue

            pnl = row["realized_pnl"]
            r_before = f"{pnl / old_risk:+.4f}R" if pnl is not None and old_risk else "-"
            r_after = f"{pnl / new_risk:+.2f}R" if pnl is not None else "open"
            print(f"{label}: entry 0 -> {entry}  |  risk ${old_risk or 0:,.2f} -> ${new_risk:.2f} "
                  f"(today's tick value says ${check or 0:.2f})  |  pnl {pnl}: {r_before} -> {r_after}")
            fixes.append((row["id"], entry, new_risk))
    finally:
        broker.disconnect()

    if not args.apply:
        print(f"\n{len(fixes)} row(s) would be repaired, {problems} skipped. "
              "Nothing written - run again with --apply to write.")
        return 0 if not problems else 1

    for trade_id, entry, risk in fixes:
        supabase.update("trades", {"id": f"eq.{trade_id}", "entry_price": "lte.0"},
                        {"entry_price": entry, "risk_amount": round(risk, 6)})
    left = supabase.count("trades", {"account_key": f"eq.{account}", "entry_price": "lte.0"})
    print(f"\n{len(fixes)} row(s) repaired, {problems} skipped. "
          f"{left} trade(s) still recorded at entry 0 for {account}.")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
