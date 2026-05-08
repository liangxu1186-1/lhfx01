"""Utilities for aggregating complete execution candles into strategy candles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import CanonicalCandle
from crypto_backtest_workbench.engine.data.canonicalizer import sort_and_deduplicate_candles


def merge_complete_execution_strategy_candles(
    *,
    strategy_candles: list[CanonicalCandle],
    execution_candles: list[CanonicalCandle],
    source_timeframe: str,
    target_timeframe: str,
    until: datetime,
) -> list[CanonicalCandle]:
    aggregated = aggregate_complete_execution_candles(
        execution_candles,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        until=until,
    )
    if not aggregated:
        return strategy_candles
    return sort_and_deduplicate_candles([*strategy_candles, *aggregated])


def aggregate_complete_execution_candles(
    candles: list[CanonicalCandle],
    *,
    source_timeframe: str,
    target_timeframe: str,
    until: datetime,
) -> list[CanonicalCandle]:
    source_delta = timeframe_delta(source_timeframe)
    target_delta = timeframe_delta(target_timeframe)
    if source_delta <= timedelta(0) or target_delta <= source_delta:
        return []
    expected_bars = int(target_delta / source_delta)
    if expected_bars <= 0 or target_delta % source_delta != timedelta(0):
        return []

    buckets: dict[datetime, dict[datetime, CanonicalCandle]] = {}
    for candle in candles:
        candle_time = candle.timestamp.astimezone(UTC)
        start = bucket_start(candle_time, target_delta)
        buckets.setdefault(start, {})[candle_time] = candle

    closed_until = until.astimezone(UTC)
    aggregated: list[CanonicalCandle] = []
    for start, bucket in sorted(buckets.items()):
        if start + target_delta > closed_until:
            continue
        expected_timestamps = {start + (source_delta * index) for index in range(expected_bars)}
        if set(bucket) != expected_timestamps:
            continue
        ordered = [bucket[timestamp] for timestamp in sorted(expected_timestamps)]
        aggregated.append(
            CanonicalCandle(
                timestamp=start,
                symbol=ordered[0].symbol,
                exchange=ordered[0].exchange,
                market_type=ordered[0].market_type,
                timeframe=target_timeframe.strip().lower(),
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=sum(item.volume for item in ordered),
                price_type=ordered[0].price_type,
                data_source="aggregated_complete_execution_klines",
            )
        )
    return aggregated


def bucket_start(timestamp: datetime, target_delta: timedelta) -> datetime:
    current = timestamp.astimezone(UTC)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = current - midnight
    bucket_index = elapsed // target_delta
    return midnight + (target_delta * bucket_index)


def timeframe_delta(timeframe: str) -> timedelta:
    normalized = timeframe.strip().lower()
    if normalized.endswith("m"):
        return timedelta(minutes=int(normalized[:-1]))
    if normalized.endswith("h"):
        return timedelta(hours=int(normalized[:-1]))
    if normalized.endswith("d"):
        return timedelta(days=int(normalized[:-1]))
    raise ValueError(f"unsupported timeframe: {timeframe}")
