r"""A filled order must be recorded at the price it filled at - never 0.

    .venv\Scripts\python.exe scripts\test_fill_price.py

place_order() used to record MT5's result.price as the entry. The demo server
puts the fill there; the LIVE server puts 0.0. Every live trade was saved as
opened at 0, so risk_amount came out as |0 - stop| x value x lots - ~2,400x too
large - and a real ~-1R stop-out read as -0.0005R. Found 2026-09-16 on all 5
live london_breakout_v1 trades, against 0 of ~100 demo trades.

Uses a fake MetaTrader5 that behaves like each server, the numbers from the
first live trade (EURGBP, 0.07 lot, 2026-09-09), and the real code paths.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import types
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- a fake MetaTrader5, installed before anything imports the real one ------
fake = types.ModuleType("MetaTrader5")
fake.ORDER_TYPE_BUY, fake.ORDER_TYPE_SELL = 0, 1
fake.TRADE_ACTION_DEAL, fake.ORDER_FILLING_IOC, fake.ORDER_TIME_GTC = 1, 1, 0
fake.TRADE_RETCODE_DONE, fake.DEAL_ENTRY_IN = 10009, 0
fake.last_error = lambda: (1, "Success")

ASK, BID = 0.85903, 0.85895
ORDER, DEAL = 1_100_200_300, 900_800_700
SERVER = {}


def _order_send(request):
    return types.SimpleNamespace(retcode=SERVER.get("retcode", 10009), order=ORDER, deal=DEAL,
                                 price=SERVER["result_price"], comment="")


def _positions_get(ticket=None):
    if SERVER.get("lookup_raises"):
        raise RuntimeError("IPC hiccup")
    price = SERVER.get("position_price")
    return (types.SimpleNamespace(price_open=price),) if price else ()


def _history_deals_get(ticket=None):
    price = SERVER.get("deal_price")
    return (types.SimpleNamespace(price=price),) if price else ()


fake.symbol_info_tick = lambda symbol: types.SimpleNamespace(ask=ASK, bid=BID, time=0, time_msc=0)
fake.order_send = _order_send
fake.positions_get = _positions_get
fake.history_deals_get = _history_deals_get
sys.modules["MetaTrader5"] = fake

from engine.core.models import Direction                          # noqa: E402
from engine.loop import EngineLoop                                 # noqa: E402
from engine.plugins.brokers.mt5_broker import (                    # noqa: E402
    MT5BrokerAdapter, MT5ConnectionError,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repair_entry_prices as repair                               # noqa: E402

logging.disable(logging.CRITICAL)

# The first live trade, as recorded: entry 0, stop 0.858613836486105, risk $8,139.56.
STOP = 0.858613836486105
BAD_RISK = 8139.56472236626
LOTS = 0.07
VALUE_PER_LOT = BAD_RISK / STOP / LOTS   # what the engine captured at open


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def place(direction=Direction.LONG, **server):
    SERVER.clear()
    SERVER.update(server)
    broker = object.__new__(MT5BrokerAdapter)
    try:
        return broker.place_order("EURGBP", direction, LOTS, STOP, 0.8595)
    except Exception as exc:          # reported, not crashed on
        return exc


def entry_of(position):
    return position.entry_price if hasattr(position, "entry_price") else f"raised {position!r}"


def main() -> int:
    passed = []

    print("demo server - result.price carries the fill (behaviour unchanged)")
    passed.append(check("entry is result.price", entry_of(place(result_price=0.85901)), 0.85901))

    print("\nlive server - result.price is 0.0, the position knows the fill")
    live = place(result_price=0.0, position_price=0.85904, deal_price=0.85904)
    passed.append(check("entry is the position's price_open, not 0", entry_of(live), 0.85904))

    print("\nlive server - position not visible yet, the deal is")
    passed.append(check("entry is the deal price", entry_of(place(result_price=0.0, deal_price=0.85906)), 0.85906))

    print("\nlive server - neither lookup answers")
    passed.append(check("LONG falls back to the ask we sent", entry_of(place(result_price=0.0)), ASK))
    passed.append(check("SHORT falls back to the bid we sent",
                        entry_of(place(Direction.SHORT, result_price=0.0)), BID))

    print("\nthe lookup itself fails - the order is ALREADY FILLED")
    failed_lookup = place(result_price=0.0, lookup_raises=True)
    passed.append(check("still returns the open position (not reported as a failed order)",
                        type(failed_lookup).__name__, "Position"))
    passed.append(check("recorded at the price we sent", entry_of(failed_lookup), ASK))

    print("\na refused order is still an error")
    passed.append(check("retcode 10016 raises", type(place(result_price=0.0, retcode=10016)).__name__,
                        MT5ConnectionError.__name__))

    print("\nrisk_amount from the position the engine now records")
    loop = object.__new__(EngineLoop)
    loop._engine = types.SimpleNamespace(broker=types.SimpleNamespace(
        get_price_value_per_lot=lambda symbol: VALUE_PER_LOT))
    risk = loop._risk_amount(live)
    passed.append(check(f"a few dollars, not $8,139 (got ${risk:,.2f})", 3.0 < risk < 4.5, True))
    zero = types.SimpleNamespace(id="x", symbol="EURGBP", entry_price=0.0, stop_loss=STOP, lot_size=LOTS)
    passed.append(check("an entry of 0 yields no risk_amount rather than a wrong one",
                        loop._risk_amount(zero), None))

    print("\nrepairing the rows already saved")
    rebuilt = repair.repaired_risk(BAD_RISK, STOP, 0.85904)
    direct = VALUE_PER_LOT * LOTS * abs(0.85904 - STOP)
    passed.append(check(f"rebuilt risk matches value x lots x distance (${rebuilt:.4f})",
                        round(rebuilt, 9), round(direct, 9)))
    passed.append(check("realised -$4.20 becomes about -1.0R, not -0.0005R",
                        round(-4.2 / rebuilt, 1), -1.0))
    passed.append(check("LONG stop below entry is on the losing side",
                        repair.stop_on_losing_side("LONG", 0.85904, STOP), True))
    passed.append(check("SHORT with the stop below entry is rejected",
                        repair.stop_on_losing_side("SHORT", 0.85904, STOP), False))

    print("\nthe repair refuses while the engine is attached to the terminal")
    repair.ROOT = Path(mkdtemp(prefix="repair-"))
    (repair.ROOT / "logs").mkdir()
    pid_file = repair.ROOT / "logs" / "engine-icmarkets-live.pid"
    passed.append(check("no pid file -> not running", repair.engine_running("icmarkets-live"), None))
    pid_file.write_text(f"{os.getpid()}\n2026-09-16T00:00:00+00:00\n", encoding="utf-8")
    passed.append(check("a live python process -> running", repair.engine_running("icmarkets-live"), os.getpid()))
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    pid_file.write_text(f"{gone.pid}\n2026-09-16T00:00:00+00:00\n", encoding="utf-8")
    passed.append(check("a stale pid file (engine killed by Stop-ScheduledTask) -> not running",
                        repair.engine_running("icmarkets-live"), None))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
