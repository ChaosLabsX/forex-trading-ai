r"""Every closed trade records how it ended and how far it went - and a close never waits on it.

    .venv\Scripts\python.exe scripts\test_trade_autopsy.py

Covers the broker's reading of MT5 deals (summarize_closed_deals, with MT5's
real constants), the pure rules in engine/trade_autopsy.py, the Telegram line,
and the engine's close path end to end with fakes - including the case that
matters most: if the autopsy write fails (migration 0017 not yet applied), the
trade is still marked CLOSED.
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MetaTrader5 as mt5                                                        # noqa: E402

from engine import trade_autopsy as ta                                           # noqa: E402
from engine.core.models import Candle, ClosedTradePnl, Direction, Timeframe      # noqa: E402
from engine.loop import EngineLoop                                               # noqa: E402
from engine.plugins.brokers.mt5_broker import summarize_closed_deals             # noqa: E402
from engine.reporting import trade_closed                                        # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def deal(entry, reason=mt5.DEAL_REASON_CLIENT, price=1.1, volume=0.05, profit=0.0, commission=-0.18, swap=0.0, t=0):
    return types.SimpleNamespace(entry=entry, reason=reason, price=price, volume=volume, profit=profit,
                                 commission=commission, swap=swap, time=t)


def minute_bars(lows_highs, start=T0):
    return [Candle("EURGBP", Timeframe.M1, start + timedelta(minutes=i), (lo + hi) / 2, hi, lo, (lo + hi) / 2, 1)
            for i, (lo, hi) in enumerate(lows_highs)]


class FakeSupabase:
    def __init__(self, open_rows=(), fail_first_update=False, fail_all_updates=False):
        self.open_rows, self.updates = list(open_rows), []
        self.fail_first, self.fail_all = fail_first_update, fail_all_updates

    def select(self, table, filters):
        return [dict(r) for r in self.open_rows]

    def update(self, table, where, values):
        self.updates.append((table, dict(where), dict(values)))
        if self.fail_all or (self.fail_first and len(self.updates) == 1):
            raise RuntimeError("column trades.exit_reason does not exist")


def bare_loop(**attrs) -> EngineLoop:
    loop = EngineLoop.__new__(EngineLoop)
    for k, v in attrs.items():
        setattr(loop, k, v)
    return loop


def main() -> int:
    logging.disable(logging.CRITICAL)  # failure cases log on purpose
    passed = []
    to_utc = lambda epoch: datetime.fromtimestamp(epoch, UTC)  # noqa: E731

    print("reading MT5 deals")
    passed.append(check("no deals: None", summarize_closed_deals((), to_utc), None))
    passed.append(check("no closing deal yet: None", summarize_closed_deals((deal(mt5.DEAL_ENTRY_IN),), to_utc), None))
    b = summarize_closed_deals((deal(mt5.DEAL_ENTRY_IN, price=0.85646),
                                deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_SL, price=0.85694, profit=-3.55, t=1_760_000_000)),
                               to_utc)
    passed.append(check("P&L exactly as before (gross, commission on both deals, swap)",
                        (round(b.gross_profit, 2), round(b.commission, 2), b.swap, round(b.net, 2)),
                        (-3.55, -0.36, 0.0, -3.91)))
    passed.append(check("exit price and how: the stop-loss fill", (b.exit_price, b.exit_how), (0.85694, "sl")))
    passed.append(check("exit time from the closing deal", b.exit_time, datetime.fromtimestamp(1_760_000_000, UTC)))
    b = summarize_closed_deals((deal(mt5.DEAL_ENTRY_IN, volume=0.04),
                                deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_TP, price=1.2000, volume=0.01),
                                deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_TP, price=1.2010, volume=0.03)), to_utc)
    passed.append(check("partial closes: volume-weighted exit price", round(b.exit_price, 6), 1.20075))
    passed.append(check("phone close counts as by hand",
                        summarize_closed_deals((deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_MOBILE),), to_utc).exit_how, "client"))
    passed.append(check("rollover or anything else: 'other'",
                        summarize_closed_deals((deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_ROLLOVER),), to_utc).exit_how, "other"))
    def no_clock(_):
        raise RuntimeError("server time unavailable")
    b = summarize_closed_deals((deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_REASON_SL, profit=-2.0),), no_clock)
    passed.append(check("unreadable clock costs only the exit time", (b.exit_time, b.gross_profit, b.exit_how),
                        (None, -2.0, "sl")))

    print("\nnaming how it ended")
    L, S = Direction.LONG, Direction.SHORT
    passed.append(check("TP fill: target", ta.classify_exit(L, 1.10, 1.09, 1.115, "tp"), "target"))
    passed.append(check("SL fill at the original stop: stop", ta.classify_exit(L, 1.10, 1.09, 1.0899, "sl"), "stop"))
    passed.append(check("SL fill at entry: breakeven", ta.classify_exit(L, 1.10, 1.09, 1.0999, "sl"), "breakeven"))
    passed.append(check("SL fill at +1R: trailing stop", ta.classify_exit(L, 1.10, 1.09, 1.11, "sl"), "trailing_stop"))
    passed.append(check("short, SL at the original stop: stop", ta.classify_exit("SHORT", 1.10, 1.11, 1.1101, "sl"), "stop"))
    passed.append(check("short, SL at entry: breakeven", ta.classify_exit(S, 1.10, 1.11, 1.1001, "sl"), "breakeven"))
    passed.append(check("closed by hand / by the engine / stop-out",
                        [ta.classify_exit(L, 1.1, 1.09, 1.1, h) for h in ("client", "expert", "stop_out")],
                        ["manual", "engine", "stop_out"]))
    passed.append(check("nothing known: unknown", ta.classify_exit(L, 1.1, 1.09, None, None), "unknown"))

    print("\nhow far it went")
    bars = minute_bars([(0.9998, 1.0004), (0.9994, 1.0008), (0.9992, 1.0001)])
    passed.append(check("long: best +0.8R, worst -0.8R (risk 10 pips)", ta.excursions(L, 1.0, 0.999, bars), (0.8, -0.8)))
    passed.append(check("short: best +0.8R, worst -0.8R", ta.excursions(S, 1.0, 1.001, bars), (0.8, -0.8)))
    passed.append(check("never moved our way: best is 0, not negative",
                        ta.excursions(L, 1.0, 0.999, minute_bars([(0.9993, 0.99995)])), (0.0, -0.7)))
    passed.append(check("no bars: nothing measured", ta.excursions(L, 1.0, 0.999, []), (None, None)))
    passed.append(check("entry recorded as 0 (the old live bug): nothing measured",
                        ta.excursions(L, 0.0, 0.999, bars), (None, None)))
    window = minute_bars([(1, 1)] * 10, start=T0 - timedelta(minutes=3))
    kept = ta.bars_during(window, Timeframe.M1, T0 + timedelta(seconds=30), T0 + timedelta(minutes=4, seconds=10))
    passed.append(check("window: the entry minute through the exit minute",
                        (kept[0].time, kept[-1].time), (T0, T0 + timedelta(minutes=4))))
    passed.append(check("2-hour-old trade: 1-minute bars", ta.bars_request(T0, T0 + timedelta(hours=2)), (Timeframe.M1, 130)))
    passed.append(check("5-week-old trade: 1-minute bars still reach",
                        ta.bars_request(T0, T0 + timedelta(days=35))[0], Timeframe.M1))
    passed.append(check("90-day-old trade: 5-minute bars", ta.bars_request(T0, T0 + timedelta(days=90))[0], Timeframe.M5))
    passed.append(check("1 year back: 15-minute bars", ta.bars_request(T0, T0 + timedelta(days=365))[0], Timeframe.M15))

    print("\nthe Telegram line")
    pnl_loss = ClosedTradePnl(-3.55, -0.36, 0.0)
    pnl_win = ClosedTradePnl(4.33, -0.36, 0.0)
    note = ta.describe({"exit_reason": "stop", "max_favorable_r": 0.62})
    passed.append(check("describe a full stop", note, "full stop, best was +0.6R"))
    passed.append(check("describe a target", ta.describe({"exit_reason": "target", "max_favorable_r": 1.5}), "hit target"))
    passed.append(check("loss alert carries the note",
                        trade_closed("EURGBP", "SHORT", pnl_loss, "london_breakout_v1", "LIVE", exit_note=note).splitlines()[-1],
                        "incl. fees  ·  full stop, best was +0.6R"))
    passed.append(check("win alert carries the note",
                        trade_closed("USDCAD", "LONG", pnl_win, "london_breakout_v1", "LIVE", exit_note="hit target").splitlines()[-1],
                        "before fees  ·  fees -$0.36  ·  hit target"))
    passed.append(check("no note: the alert is exactly as before",
                        trade_closed("EURGBP", "SHORT", pnl_loss, "london_breakout_v1", "LIVE").splitlines()[-1], "incl. fees"))

    print("\nthe engine's close: the autopsy rides along, and never blocks it")
    row = {"mt5_ticket": "4636539529", "strategy_name": "london_breakout_v1", "symbol": "EURGBP",
           "direction": "SHORT", "entry_price": 0.85646, "initial_stop_loss": 0.85694, "stop_loss": 0.85694,
           "opened_at": (T0).isoformat()}
    exit_pnl = ClosedTradePnl(-3.55, -0.36, 0.0, exit_price=0.85694, exit_how="sl", exit_time=T0 + timedelta(minutes=2))
    path = minute_bars([(0.85620, 0.85650), (0.85636, 0.85700), (0.85690, 0.85710)])
    messages = []
    def engine_for(md):
        notifier = types.SimpleNamespace(notify=lambda event: messages.append(event.message))
        broker = types.SimpleNamespace(get_closed_position_breakdown=lambda ticket: exit_pnl)
        return types.SimpleNamespace(broker=broker, market_data=md, notifications=[notifier])
    good_md = types.SimpleNamespace(get_candles=lambda symbol, tf, count: path)
    db = FakeSupabase([row])
    loop = bare_loop(_engine=engine_for(good_md), _supabase=db, _account_key="icmarkets-live")
    loop._account_label = lambda: "LIVE"
    loop._reconcile_closed_trades(open_positions=[])
    values = db.updates[-1][2]
    passed.append(check("one write, CLOSED with its P&L", (len(db.updates), values["status"], round(values["realized_pnl"], 2)),
                        (1, "CLOSED", -3.91)))
    passed.append(check("...and its autopsy in the same write",
                        (values["exit_reason"], values["exit_price"], values["max_favorable_r"], values["max_adverse_r"]),
                        ("stop", 0.85694, 0.542, -1.333)))
    passed.append(check("Telegram says how it ended", messages[-1].splitlines()[-1], "incl. fees  ·  full stop, best was +0.5R"))

    db = FakeSupabase([row], fail_first_update=True)
    loop = bare_loop(_engine=engine_for(good_md), _supabase=db, _account_key="icmarkets-live")
    loop._account_label = lambda: "LIVE"
    loop._reconcile_closed_trades(open_positions=[])
    passed.append(check("columns missing (0017 not applied): retried WITHOUT the autopsy, still CLOSED",
                        (len(db.updates), db.updates[1][2]["status"], "exit_reason" in db.updates[1][2]), (2, "CLOSED", False)))

    def broken_md(*a):
        raise RuntimeError("no price feed")
    db = FakeSupabase([row])
    loop = bare_loop(_engine=engine_for(types.SimpleNamespace(get_candles=broken_md)), _supabase=db, _account_key="x")
    loop._account_label = lambda: "LIVE"
    loop._reconcile_closed_trades(open_positions=[])
    values = db.updates[-1][2]
    passed.append(check("no price feed: exit reason kept, excursions left out, still CLOSED",
                        (values["status"], values.get("exit_reason"), "max_favorable_r" in values), ("CLOSED", "stop", False)))

    passed.append(check("no breakdown from MT5: no autopsy, no crash", bare_loop()._trade_autopsy(row, None), {}))
    still_open = FakeSupabase([row])
    loop = bare_loop(_engine=engine_for(good_md), _supabase=still_open, _account_key="x")
    loop._reconcile_closed_trades(open_positions=[types.SimpleNamespace(id="4636539529")])
    passed.append(check("a still-open trade is not touched", still_open.updates, []))

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
