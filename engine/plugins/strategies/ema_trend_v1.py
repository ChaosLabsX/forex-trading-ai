from __future__ import annotations

from engine.config import Settings
from engine.core.interfaces.strategy import StrategyContext, StrategyEvaluation, StrategyPlugin
from engine.core.models import Direction, PositionStatus, Signal, Timeframe
from engine.indicators import adx, atr, ema_series

REGIME_TIMEFRAME = Timeframe.H4
ENTRY_TIMEFRAME = Timeframe.H1
REGIME_FAST_EMA = 50
REGIME_SLOW_EMA = 200
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 20
ENTRY_FAST_EMA = 20
ENTRY_SLOW_EMA = 50
ATR_PERIOD = 14
STOP_ATR_MULTIPLE = 1.5
TARGET_ATR_MULTIPLE = 2.0

# London/NY session overlap, UTC. Outside this window liquidity is thinner and
# spreads on these instruments are typically worse.
SESSION_START_UTC_HOUR = 12
SESSION_END_UTC_HOUR = 16

NEWS_BLACKOUT_MINUTES = 30
# Widened from 4 symbols to 16. The logic is unchanged - this is purely a data
# rate decision. At 4 symbols this strategy produced ~19 trades/year, so the
# lab's 100-trade bar was ~5 years away and the verdict would never arrive.
# Same idea, more independent samples of it, sooner.
#
# Caveat worth knowing: these are NOT statistically independent. EURUSD, GBPUSD
# and EURGBP share drivers, so correlated signals inflate the apparent sample.
# The bootstrap CI assumes independence and will therefore read slightly tighter
# than reality. It's a real limitation, and still far better than 19/year.
INSTRUMENT_CURRENCIES = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("USD",),
    "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "USDCHF": ("USD", "CHF"),
    "NZDUSD": ("NZD", "USD"),
    "EURJPY": ("EUR", "JPY"),
    "GBPJPY": ("GBP", "JPY"),
    "EURGBP": ("EUR", "GBP"),
    "AUDJPY": ("AUD", "JPY"),
    "EURAUD": ("EUR", "AUD"),
    "GBPAUD": ("GBP", "AUD"),
    "CADJPY": ("CAD", "JPY"),
    "CHFJPY": ("CHF", "JPY"),
}


class EMATrendStrategy(StrategyPlugin):
    """Reference StrategyPlugin implementation - first plugin used to build and
    test the rest of the platform, not what the engine is designed around.

    H4 EMA(50/200) regime + ADX(14) trend-strength gate, H1 EMA(20/50)
    crossover entry in the regime's direction, ATR(14)-based stop/target.
    See PLAN.md for the full rationale.
    """

    name = "ema_trend_v1"
    required_timeframes = (ENTRY_TIMEFRAME, REGIME_TIMEFRAME)
    instruments = tuple(INSTRUMENT_CURRENCIES)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, context: StrategyContext) -> StrategyEvaluation:
        if any(
            p.symbol == context.symbol and p.status == PositionStatus.OPEN
            for p in context.open_positions
        ):
            return StrategyEvaluation(None, "position already open for this symbol")

        h4 = context.candles_by_timeframe.get(REGIME_TIMEFRAME, [])
        h1 = context.candles_by_timeframe.get(ENTRY_TIMEFRAME, [])
        if len(h4) < REGIME_SLOW_EMA + 1 or len(h1) < ENTRY_SLOW_EMA + 1:
            return StrategyEvaluation(None, "insufficient candle history for indicators")

        latest_bar_time = h1[-1].time
        if not (SESSION_START_UTC_HOUR <= latest_bar_time.hour < SESSION_END_UTC_HOUR):
            return StrategyEvaluation(
                None, f"outside London/NY session overlap (bar hour {latest_bar_time.hour:02d}:00 UTC)"
            )

        relevant_currencies = INSTRUMENT_CURRENCIES.get(context.symbol, ())
        for event in context.upcoming_news:
            if event.currency not in relevant_currencies or event.impact != "high":
                continue
            minutes_away = abs((event.time - latest_bar_time).total_seconds()) / 60
            if minutes_away <= NEWS_BLACKOUT_MINUTES:
                return StrategyEvaluation(
                    None, f"news blackout: {event.currency} '{event.title}' within {NEWS_BLACKOUT_MINUTES}min"
                )

        ema_fast_h4 = ema_series([c.close for c in h4], REGIME_FAST_EMA)[-1]
        ema_slow_h4 = ema_series([c.close for c in h4], REGIME_SLOW_EMA)[-1]
        adx_h4 = adx(h4, ADX_PERIOD)
        if ema_fast_h4 is None or ema_slow_h4 is None or adx_h4 is None:
            return StrategyEvaluation(None, "insufficient H4 history for regime indicators")

        if adx_h4 < ADX_TREND_THRESHOLD:
            return StrategyEvaluation(
                None, f"ADX({adx_h4:.1f}) below trend-strength threshold ({ADX_TREND_THRESHOLD}) on H4"
            )

        if ema_fast_h4 > ema_slow_h4:
            regime = Direction.LONG
        elif ema_fast_h4 < ema_slow_h4:
            regime = Direction.SHORT
        else:
            return StrategyEvaluation(None, "no clear H4 regime (EMA50 == EMA200)")

        h1_closes = [c.close for c in h1]
        ema_fast_series = ema_series(h1_closes, ENTRY_FAST_EMA)
        ema_slow_series = ema_series(h1_closes, ENTRY_SLOW_EMA)
        if any(v is None for v in (ema_fast_series[-1], ema_fast_series[-2], ema_slow_series[-1], ema_slow_series[-2])):
            return StrategyEvaluation(None, "insufficient H1 history for entry crossover detection")

        prev_diff = ema_fast_series[-2] - ema_slow_series[-2]
        curr_diff = ema_fast_series[-1] - ema_slow_series[-1]
        bullish_cross = prev_diff <= 0 < curr_diff
        bearish_cross = prev_diff >= 0 > curr_diff

        if bullish_cross and regime == Direction.LONG:
            direction = Direction.LONG
        elif bearish_cross and regime == Direction.SHORT:
            direction = Direction.SHORT
        elif bullish_cross or bearish_cross:
            return StrategyEvaluation(
                None, f"H1 EMA(20/50) crossover detected but conflicts with H4 regime ({regime.value})"
            )
        else:
            return StrategyEvaluation(None, "no fresh H1 EMA(20/50) crossover this bar")

        atr_h1 = atr(h1, ATR_PERIOD)
        if atr_h1 is None:
            return StrategyEvaluation(None, "insufficient H1 history for ATR(14)")

        entry_price = h1[-1].close
        stop_distance = STOP_ATR_MULTIPLE * atr_h1
        target_distance = TARGET_ATR_MULTIPLE * atr_h1
        if direction == Direction.LONG:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + target_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - target_distance

        reason = (
            f"H4 regime={regime.value} (EMA{REGIME_FAST_EMA}={ema_fast_h4:.5f} vs "
            f"EMA{REGIME_SLOW_EMA}={ema_slow_h4:.5f}, ADX={adx_h4:.1f}); "
            f"H1 EMA({ENTRY_FAST_EMA}/{ENTRY_SLOW_EMA}) {direction.value.lower()} crossover; "
            f"ATR{ATR_PERIOD}={atr_h1:.5f}"
        )
        signal = Signal(
            strategy_name=self.name,
            symbol=context.symbol,
            direction=direction,
            timeframe=ENTRY_TIMEFRAME,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason,
            metadata={"adx_h4": adx_h4, "atr_h1": atr_h1},
        )
        return StrategyEvaluation(signal, reason)
