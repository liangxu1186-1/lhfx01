from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    FeatureSpec,
    MarketType,
)
from crypto_backtest_workbench.engine.features import (
    FeatureCacheRegistry,
    FeaturePipeline,
    compute_ema,
    compute_rsi,
)
from crypto_backtest_workbench.storage.repositories import FileFeatureRepository


def test_compute_ema_uses_sma_seed_and_leading_none() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    result = compute_ema(values, window=3)

    assert result == [None, None, 2.0, 3.0, 4.0]


def test_compute_rsi_matches_expected_wilder_progression() -> None:
    values = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]

    result = compute_rsi(values, window=2)

    assert result[:2] == [None, None]
    assert result[2:] == [50.0, 75.0, 37.5, 68.75]


def test_feature_pipeline_materializes_and_persists_feature_rows(tmp_path) -> None:
    repository = FileFeatureRepository(tmp_path)
    pipeline = FeaturePipeline(repository, cache_registry=FeatureCacheRegistry())
    candles = build_candles([1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
    specs = [
        FeatureSpec(name="ema", params={"window": 3}),
        FeatureSpec(name="rsi", params={"window": 2}),
    ]

    artifact = pipeline.materialize(
        dataset_snapshot_id="snapshot-001",
        candles=candles,
        specs=specs,
        depends_on=("dataset-raw",),
    )

    assert artifact.dataset_snapshot_id == "snapshot-001"
    assert artifact.feature_version == "feature-pipeline-v1__ema-v1__rsi-v1"
    assert artifact.warmup_bars == 3
    assert artifact.depends_on == ("dataset-raw",)
    assert artifact.storage_uri.endswith("feature_rows.csv")

    feature_names, rows = repository.load_feature_rows(artifact.feature_artifact_id)
    assert feature_names == ("ema_close_3", "rsi_close_2")
    assert len(rows) == len(candles)
    assert rows[0].values == {"ema_close_3": None, "rsi_close_2": None}
    assert rows[2].values["ema_close_3"] == 4.0 / 3.0
    assert rows[3].values["rsi_close_2"] == 75.0
    assert rows[-1].values["ema_close_3"] == pytest.approx(5.0 / 3.0)
    assert rows[-1].values["rsi_close_2"] == 68.75


def test_feature_pipeline_reuses_persisted_artifact_for_same_cache_key(tmp_path) -> None:
    repository = FileFeatureRepository(tmp_path)
    candles = build_candles([10.0, 11.0, 12.0, 13.0, 14.0])
    specs = [FeatureSpec(name="ema", params={"window": 3})]

    first = FeaturePipeline(repository).materialize(
        dataset_snapshot_id="snapshot-001",
        candles=candles,
        specs=specs,
    )
    second = FeaturePipeline(repository).materialize(
        dataset_snapshot_id="snapshot-001",
        candles=candles,
        specs=specs,
    )

    assert second.feature_artifact_id == first.feature_artifact_id
    assert second.feature_cache_key == first.feature_cache_key
    assert len(list((tmp_path / "features").glob("feature-*/artifact.json"))) == 1


def build_candles(close_prices: list[float]) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, close_price in enumerate(close_prices):
        timestamp = start + timedelta(hours=index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=close_price,
                high=close_price,
                low=close_price,
                close=close_price,
                volume=100.0,
            )
        )
    return candles
