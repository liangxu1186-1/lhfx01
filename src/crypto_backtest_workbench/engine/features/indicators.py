"""Lightweight feature indicator implementations for Phase 1."""

from __future__ import annotations

from typing import Sequence


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


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        if avg_gain == 0.0:
            return 50.0
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))
