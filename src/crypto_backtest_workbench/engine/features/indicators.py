"""Lightweight feature indicator implementations for Phase 1."""

from __future__ import annotations

from typing import Sequence

from crypto_backtest_workbench.domain.models import CanonicalCandle


def compute_ema(values: Sequence[float], window: int) -> list[float | None]:
    """Compute EMA with an SMA seed and leading ``None`` before the window is ready."""

    if window <= 0:
        raise ValueError("EMA window must be positive")

    length = len(values)
    if length == 0:
        return []
    if length < window:
        return [None] * length

    result: list[float | None] = [None] * length
    multiplier = 2.0 / (window + 1)
    seed = sum(values[:window]) / window
    result[window - 1] = seed
    ema_value = seed

    for index in range(window, length):
        ema_value = ((values[index] - ema_value) * multiplier) + ema_value
        result[index] = ema_value

    return result


def compute_rsi(values: Sequence[float], window: int) -> list[float | None]:
    """Compute Wilder RSI with leading ``None`` until the window is ready."""

    if window <= 0:
        raise ValueError("RSI window must be positive")

    length = len(values)
    if length == 0:
        return []
    if length <= window:
        return [None] * length

    result: list[float | None] = [None] * length
    gains = [0.0] * length
    losses = [0.0] * length

    for index in range(1, length):
        change = values[index] - values[index - 1]
        gains[index] = max(change, 0.0)
        losses[index] = max(-change, 0.0)

    avg_gain = sum(gains[1 : window + 1]) / window
    avg_loss = sum(losses[1 : window + 1]) / window
    result[window] = _rsi_from_averages(avg_gain, avg_loss)

    for index in range(window + 1, length):
        avg_gain = ((avg_gain * (window - 1)) + gains[index]) / window
        avg_loss = ((avg_loss * (window - 1)) + losses[index]) / window
        result[index] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def compute_atr(candles: Sequence[CanonicalCandle], window: int) -> list[float | None]:
    """Compute ATR with True Range, SMA seed, and Wilder smoothing."""

    if window <= 0:
        raise ValueError("ATR window must be positive")

    length = len(candles)
    if length == 0:
        return []
    if length < window:
        return [None] * length

    true_ranges: list[float] = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(float(candle.high - candle.low))
            continue
        previous_close = float(candles[index - 1].close)
        true_ranges.append(
            max(
                float(candle.high - candle.low),
                abs(float(candle.high) - previous_close),
                abs(float(candle.low) - previous_close),
            )
        )

    result: list[float | None] = [None] * length
    atr_value = sum(true_ranges[:window]) / window
    result[window - 1] = atr_value
    for index in range(window, length):
        atr_value = ((atr_value * (window - 1)) + true_ranges[index]) / window
        result[index] = atr_value
    return result


def compute_adx(candles: Sequence[CanonicalCandle], window: int) -> list[float | None]:
    """Compute Wilder ADX from canonical candles."""

    if window <= 0:
        raise ValueError("ADX window must be positive")

    length = len(candles)
    if length == 0:
        return []
    if length < (window * 2):
        return [None] * length

    true_ranges: list[float] = [0.0] * length
    plus_dm: list[float] = [0.0] * length
    minus_dm: list[float] = [0.0] * length
    for index in range(1, length):
        current = candles[index]
        previous = candles[index - 1]
        high_move = float(current.high - previous.high)
        low_move = float(previous.low - current.low)
        plus_dm[index] = high_move if high_move > low_move and high_move > 0 else 0.0
        minus_dm[index] = low_move if low_move > high_move and low_move > 0 else 0.0
        previous_close = float(previous.close)
        true_ranges[index] = max(
            float(current.high - current.low),
            abs(float(current.high) - previous_close),
            abs(float(current.low) - previous_close),
        )

    result: list[float | None] = [None] * length
    tr_smooth = sum(true_ranges[1 : window + 1])
    plus_smooth = sum(plus_dm[1 : window + 1])
    minus_smooth = sum(minus_dm[1 : window + 1])
    dx_values: list[float | None] = [None] * length

    for index in range(window, length):
        if index > window:
            tr_smooth = tr_smooth - (tr_smooth / window) + true_ranges[index]
            plus_smooth = plus_smooth - (plus_smooth / window) + plus_dm[index]
            minus_smooth = minus_smooth - (minus_smooth / window) + minus_dm[index]
        if tr_smooth == 0:
            dx_values[index] = 0.0
            continue
        plus_di = 100.0 * plus_smooth / tr_smooth
        minus_di = 100.0 * minus_smooth / tr_smooth
        denominator = plus_di + minus_di
        dx_values[index] = 0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator

    first_adx_index = window * 2 - 1
    seed_values = [value for value in dx_values[window:first_adx_index + 1] if value is not None]
    if len(seed_values) < window:
        return result
    adx_value = sum(seed_values) / window
    result[first_adx_index] = adx_value
    for index in range(first_adx_index + 1, length):
        dx = dx_values[index]
        if dx is None:
            continue
        adx_value = ((adx_value * (window - 1)) + dx) / window
        result[index] = adx_value
    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        if avg_gain == 0.0:
            return 50.0
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))
