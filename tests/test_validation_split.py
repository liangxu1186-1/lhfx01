from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    MarketType,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.validation import build_validation_view


def test_build_validation_view_respects_warmup_and_default_boundaries() -> None:
    candles = _build_candles(6)
    split = ValidationSplit(
        validation_split_id="split-001",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id="snapshot-001",
        warmup_bars=2,
        is_start=candles[2].timestamp,
        is_end=candles[4].timestamp,
        oos_start=candles[4].timestamp,
        oos_end=candles[6 - 1].timestamp + timedelta(hours=1),
    )

    view = build_validation_view(candles=candles, split=split)

    assert [c.timestamp for c in view.is_segment.warmup_candles] == [
        candles[0].timestamp,
        candles[1].timestamp,
    ]
    assert [c.timestamp for c in view.is_segment.analysis_candles] == [
        candles[2].timestamp,
        candles[3].timestamp,
    ]
    assert [c.timestamp for c in view.oos_segment.warmup_candles] == [
        candles[2].timestamp,
        candles[3].timestamp,
    ]
    assert [c.timestamp for c in view.oos_segment.analysis_candles] == [
        candles[4].timestamp,
        candles[5].timestamp,
    ]
    assert view.is_segment.warmup_complete is True
    assert view.oos_segment.warmup_complete is True


def test_build_validation_view_supports_exclusive_and_inclusive_boundaries() -> None:
    candles = _build_candles(5)
    split = ValidationSplit(
        validation_split_id="split-002",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id="snapshot-001",
        warmup_bars=1,
        is_start=candles[1].timestamp,
        is_end=candles[3].timestamp,
        oos_start=candles[3].timestamp,
        oos_end=candles[4].timestamp,
        is_start_inclusive=False,
        is_end_exclusive=False,
        oos_start_inclusive=False,
        oos_end_exclusive=False,
    )

    view = build_validation_view(candles=candles, split=split)

    assert [c.timestamp for c in view.is_segment.analysis_candles] == [
        candles[2].timestamp,
        candles[3].timestamp,
    ]
    assert [c.timestamp for c in view.oos_segment.analysis_candles] == [
        candles[4].timestamp,
    ]
    assert [c.timestamp for c in view.is_segment.warmup_candles] == [
        candles[1].timestamp,
    ]
    assert view.oos_segment.warmup_complete is True


def test_build_validation_view_marks_incomplete_warmup_when_history_is_short() -> None:
    candles = _build_candles(3)
    split = ValidationSplit(
        validation_split_id="split-003",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id="snapshot-001",
        warmup_bars=3,
        is_start=candles[1].timestamp,
        is_end=candles[2].timestamp + timedelta(hours=1),
        oos_start=candles[2].timestamp,
        oos_end=candles[2].timestamp + timedelta(hours=1),
    )

    view = build_validation_view(candles=candles, split=split)

    assert len(view.is_segment.warmup_candles) == 1
    assert view.is_segment.warmup_complete is False
    assert len(view.oos_segment.warmup_candles) == 2
    assert view.oos_segment.warmup_complete is False


def _build_candles(count: int) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        CanonicalCandle(
            timestamp=start + timedelta(hours=index),
            symbol="BTC/USDT:USDT",
            exchange="binance",
            market_type=MarketType.LINEAR_USDT_PERPETUAL,
            timeframe="1h",
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=10.0,
        )
        for index in range(count)
    ]
