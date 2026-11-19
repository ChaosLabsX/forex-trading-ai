r"""range_fade_gold_v1 moves exactly one thing - the market - and never trades by accident.

    python scripts\test_range_fade_gold.py

It tests a cost argument about range_fade_v1, so its logic must be provably the
parent's: the same evaluate() function object, the same timeframes, and on
identical candles the same signal. It must run on gold alone; the backtest must
actually ask the broker for gold's full hourly history (the real code path, not
an attribute read); and it must not be loaded by either engine.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings                                              # noqa: E402
from engine.core.interfaces.strategy import StrategyContext                     # noqa: E402
from engine.core.models import AccountState, Candle, Timeframe                  # noqa: E402
from engine.indicators import adx                                               # noqa: E402
from engine.plugins.strategies.range_fade_gold_v1 import RangeFadeGoldStrategy  # noqa: E402
from engine.plugins.strategies.range_fade_v1 import RangeFadeStrategy           # noqa: E402
from engine.registry import load_plugin                                         # noqa: E402

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = AccountState(balance=1000, equity=1000, margin_used=0, open_positions_count=0,
                       daily_pnl=0, consecutive_stop_losses_today=0)


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         expected: {want}\n         actual  : {got}")
    return ok


def quiet_market(symbol: str, as_of: datetime) -> dict:
    """A range-bound market (alternating bars: ADX near zero) whose last H1 bar
    closes far below its mean - the setup range_fade fades, long."""
    h4 = []
    for i in range(60):
        t = as_of - timedelta(hours=4 * (60 - i) + 3)
        lo = 2000.0 + (2.0 if i % 2 else 0.0)
        h4.append(Candle(symbol, Timeframe.H4, t, lo + 5, lo + 10, lo, lo + 5, 1.0))
    h1 = []
    for i in range(60):
        t = as_of - timedelta(hours=59 - i)
        lo = 2000.0 + (1.0 if i % 2 else 0.0)
        h1.append(Candle(symbol, Timeframe.H1, t, lo + 2, lo + 4, lo, lo + 2, 1.0))
    last = h1[-1]
    h1[-1] = Candle(symbol, Timeframe.H1, last.time, 2002.0, 2004.0, 1989.0, 1990.0, 1.0)
    return {Timeframe.H1: h1, Timeframe.H4: h4}


def context(symbol: str, candles: dict) -> StrategyContext:
    return StrategyContext(symbol=symbol, candles_by_timeframe=candles, account_state=ACCOUNT,
                           open_positions=[], upcoming_news=())


class RecordingHistory:
    """Stands in for MT5MarketDataProvider: records what the backtest asks for
    and returns too little to trade, so run_backtest_for_symbol stops there."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, Timeframe, int]] = []

    def get_history(self, symbol, timeframe, count):
        self.asked.append((symbol, timeframe, count))
        return []


def main() -> int:
    settings = Settings()
    child, parent = RangeFadeGoldStrategy(settings), RangeFadeStrategy(settings)
    results = []

    print("the logic is the parent's, untouched")
    results.append(check("evaluate() is the same function object",
                         RangeFadeGoldStrategy.evaluate is RangeFadeStrategy.evaluate, True))
    results.append(check("same timeframes", child.required_timeframes, parent.required_timeframes))
    results.append(check("same entry / regime timeframes",
                         (child.entry_tf, child.regime_tf), (parent.entry_tf, parent.regime_tf)))
    results.append(check("own name", child.name, "range_fade_gold_v1"))
    results.append(check("built through the registry as this class",
                         type(load_plugin("strategy", "range_fade_gold_v1", settings)), RangeFadeGoldStrategy))

    print("the market is gold, alone")
    results.append(check("instruments", child.instruments, ("XAUUSD",)))

    print("on identical candles, the same signal")
    as_of = datetime(2026, 11, 10, 14, tzinfo=UTC)
    candles = quiet_market("XAUUSD", as_of)
    results.append(check("fixture is range-bound (ADX < 20)", adx(candles[Timeframe.H4], 14) < 20, True))
    a = child.evaluate(context("XAUUSD", candles)).signal
    b = parent.evaluate(context("XAUUSD", candles)).signal
    results.append(check("the child fires", a is not None, True))
    if a is not None and b is not None:
        results.append(check("direction, entry, stop, target identical",
                             (a.direction, a.entry_price, a.stop_loss, a.take_profit),
                             (b.direction, b.entry_price, b.stop_loss, b.take_profit)))
        results.append(check("signal carries the child's name", a.strategy_name, "range_fade_gold_v1"))
    night = quiet_market("XAUUSD", datetime(2026, 11, 10, 22, tzinfo=UTC))
    results.append(check("same 07-20 UTC session: silent at 22:00",
                         child.evaluate(context("XAUUSD", night)).signal, None))

    print("the backtest asks the broker for gold's full history (real code path)")
    sys.path.insert(0, str(ROOT / "scripts"))
    import backtest as bt  # noqa: E402
    md = RecordingHistory()
    bt.run_backtest_for_symbol(child, md, "XAUUSD", manager=None)
    results.append(check("child asks for 99,999 H1 bars", md.asked[:1], [("XAUUSD", Timeframe.H1, 99_999)]))
    md = RecordingHistory()
    bt.run_backtest_for_symbol(parent, md, "XAUUSD", manager=None)
    results.append(check("parent still asks for the default 20,000", md.asked[:1],
                         [("XAUUSD", Timeframe.H1, bt.ENTRY_HISTORY_BARS)]))

    print("loaded by neither engine")
    plugins = yaml.safe_load((ROOT / "config" / "plugins.yaml").read_text(encoding="utf-8"))
    results.append(check("not in config/plugins.yaml", "range_fade_gold_v1" in plugins["strategies"], False))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
