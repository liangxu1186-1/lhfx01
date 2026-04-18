from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_backtest_workbench.app.workflows.run_backtest import (
    RunBacktestWorkflowRequest,
    run_backtest_workflow,
)
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.storage.repositories import FileDatasetRepository, FileFeatureRepository


def test_run_backtest_workflow_executes_from_snapshot_and_materializes_features(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    snapshot = _persist_snapshot(
        repository=dataset_repository,
        snapshot_id="snapshot-001",
        close_prices=[100.0, 98.0, 99.0, 103.0, 104.0, 100.0, 96.0, 95.0],
    )

    result = run_backtest_workflow(
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        request=RunBacktestWorkflowRequest(
            run_id="run-001",
            snapshot=snapshot,
            strategy_params={
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
            },
            constraints=ExecutionConstraints(
                initial_cash=1_000.0,
                leverage=2.0,
                fee_rate=0.001,
                qty_by_policy={"fixed_1": 1.0},
            ),
        ),
    )

    assert len(result.candles) == 8
    assert result.feature_artifact.dataset_snapshot_id == snapshot.dataset_snapshot_id
    assert result.feature_artifact.storage_uri.endswith("feature_rows.csv")
    assert len(result.signals) == 2
    assert result.single_run_result.metrics.trade_count == 1
    assert result.single_run_result.benchmark_output is None
    assert result.single_run_result.validation_view is None
    assert result.single_run_result.run.validation_split_id == "validation:none"


def test_run_backtest_workflow_supports_validation_split_and_buy_hold_benchmark(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    close_prices = [100.0, 98.0, 99.0, 103.0, 104.0, 100.0, 96.0, 95.0]
    snapshot = _persist_snapshot(
        repository=dataset_repository,
        snapshot_id="snapshot-002",
        close_prices=close_prices,
    )
    candles = _build_candles(close_prices)
    split = ValidationSplit(
        validation_split_id="split-001",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id=snapshot.dataset_snapshot_id,
        warmup_bars=3,
        is_start=candles[2].timestamp,
        is_end=candles[6].timestamp,
        oos_start=candles[6].timestamp,
        oos_end=candles[7].timestamp + timedelta(hours=1),
    )

    result = run_backtest_workflow(
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        request=RunBacktestWorkflowRequest(
            run_id="run-002",
            snapshot=snapshot,
            strategy_params={
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
            },
            constraints=ExecutionConstraints(
                initial_cash=1_000.0,
                leverage=2.0,
                qty_by_policy={"fixed_1": 1.0},
            ),
            validation_split=split,
            enable_buy_and_hold_benchmark=True,
        ),
    )

    assert result.single_run_result.validation_view is not None
    assert [c.timestamp for c in result.single_run_result.validation_view.is_segment.analysis_candles] == [
        candles[2].timestamp,
        candles[3].timestamp,
        candles[4].timestamp,
        candles[5].timestamp,
    ]
    assert result.single_run_result.benchmark_output is not None
    assert result.single_run_result.benchmark_output.result.benchmark_type == "buy_and_hold"
    assert result.single_run_result.benchmark_output.result.return_pct == pytest.approx((100.0 - 99.0) / 99.0)
    assert result.single_run_result.run.validation_split_id == "split-001"
    assert result.single_run_result.run.status.value == "success"


def _persist_snapshot(
    *,
    repository: FileDatasetRepository,
    snapshot_id: str,
    close_prices: list[float],
) -> DatasetSnapshot:
    candles = _build_candles(close_prices)
    snapshot = DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source="binance",
        exchange="binance",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        time_range_start=candles[0].timestamp,
        time_range_end=candles[-1].timestamp,
        row_count=len(candles),
        schema_version="v1",
        feature_version="pending",
        storage_uri=f"datasets/{snapshot_id}",
        data_source="ccxt_rest",
        price_type=PriceType.LAST,
    )
    repository.save_snapshot(snapshot)
    repository.save_candles(snapshot.dataset_snapshot_id, candles)
    return snapshot


def _build_candles(close_prices: list[float]):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []
    for index, close_price in enumerate(close_prices):
        timestamp = start + timedelta(hours=index)
        candles.append(
            {
                "timestamp": timestamp,
                "symbol": "BTC/USDT:USDT",
                "exchange": "binance",
                "market_type": MarketType.LINEAR_USDT_PERPETUAL,
                "timeframe": "1h",
                "open": close_price,
                "high": close_price + 1.0,
                "low": close_price - 1.0,
                "close": close_price,
                "volume": 100.0,
            }
        )
    from crypto_backtest_workbench.domain.models import CanonicalCandle

    return [CanonicalCandle(**payload) for payload in candles]
