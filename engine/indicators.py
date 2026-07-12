from __future__ import annotations

from engine.core.models import Candle


def ema_series(values: list[float], period: int) -> list[float | None]:
    """EMA at each index; None where there isn't enough history yet."""
    if len(values) < period:
        return [None] * len(values)

    result: list[float | None] = [None] * (period - 1)
    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result.append(seed)
    prev = seed
    for value in values[period:]:
        prev = (value - prev) * multiplier + prev
        result.append(prev)
    return result


def ema(values: list[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def atr(candles: list[Candle], period: int) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for prev, curr in zip(candles, candles[1:]):
        true_ranges.append(
            max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close),
            )
        )
    # Wilder's smoothing, seeded with a simple average of the first `period` values
    window = true_ranges[-period * 3 :] if len(true_ranges) > period * 3 else true_ranges
    smoothed = sum(window[:period]) / period
    for tr in window[period:]:
        smoothed = (smoothed * (period - 1) + tr) / period
    return smoothed


def adx(candles: list[Candle], period: int) -> float | None:
    if len(candles) < period * 2 + 1:
        return None

    plus_dm = []
    minus_dm = []
    true_ranges = []
    for prev, curr in zip(candles, candles[1:]):
        up_move = curr.high - prev.high
        down_move = prev.low - curr.low
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        true_ranges.append(
            max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close))
        )

    def wilder_smooth(series: list[float]) -> list[float]:
        smoothed = [sum(series[:period])]
        for value in series[period:]:
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + value)
        return smoothed

    smoothed_tr = wilder_smooth(true_ranges)
    smoothed_plus_dm = wilder_smooth(plus_dm)
    smoothed_minus_dm = wilder_smooth(minus_dm)

    dx_values = []
    for tr, pdm, mdm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm):
        if tr == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * pdm / tr
        minus_di = 100 * mdm / tr
        di_sum = plus_di + minus_di
        dx_values.append(0.0 if di_sum == 0 else 100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        return None
    return sum(dx_values[-period:]) / period
