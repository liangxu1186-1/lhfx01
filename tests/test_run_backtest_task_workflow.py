from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.workflows import (
    RunBacktestWorkflowRequest,
    run_backtest_task_workflow,
)
from crypto_backtest_workbench.domain.models import DatasetSnapshot, MarketType, PriceType, TaskStatus
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileFeatureRepository,
    FileRunRepository,
)


def test_run_backtest_task_workflow_executes_and_persists_result(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    runner = LocalTaskRunner()
    snapshot = _persist_snapshot(
        repository=dataset_repository,
        snapshot_id="snapshot-task-001",
        close_prices=[100.0, 98.0, 99.0, 103.0, 104.0, 100.0, 96.0, 95.0],
    )

    result = run_backtest_task_workflow(
        runner=runner,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
        request=RunBacktestWorkflowRequest(
            run_id="task-run-001",
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
            enable_buy_and_hold_benchmark=True,
        ),
    )

    assert result.task.task_id == "single-run:task-run-001"
    assert result.task.status is TaskStatus.SUCCESS
    assert result.output is not None
    assert result.output.workflow_result.single_run_result.run.run_id == "task-run-001"
    assert result.output.persisted_paths["run"].exists()
    assert result.output.persisted_paths["manifest"].exists()
    assert result.output.persisted_paths["metrics"].exists()
    assert result.output.persisted_paths["execution"]["orders"].exists()
    assert result.output.persisted_paths["benchmark"]["result"].exists()
    assert runner.get_output(result.task.task_id) == result.output


def test_run_backtest_task_workflow_records_failure_for_invalid_strategy_config(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    runner = LocalTaskRunner()
    snapshot = _persist_snapshot(
        repository=dataset_repository,
        snapshot_id="snapshot-task-002",
        close_prices=[100.0, 101.0, 102.0, 103.0],
    )

    result = run_backtest_task_workflow(
        runner=runner,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
        request=RunBacktestWorkflowRequest(
            run_id="task-run-002",
            snapshot=snapshot,
            strategy_params={
                "fast_period": 4,
                "slow_period": 4,
                "qty_policy_ref": "fixed_1",
            },
            constraints=ExecutionConstraints(
                initial_cash=1_000.0,
                qty_by_policy={"fixed_1": 1.0},
            ),
        ),
    )

    assert result.output is None
    assert result.task.status is TaskStatus.FAILED
    assert result.task.failure_code is not None
    assert result.task.failure_stage == "run_backtest_task_executor"
    assert "fast_period must be smaller than slow_period" in (result.task.failure_message or "")


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
        data_source="fixture",
        price_type=PriceType.LAST,
    )
    repository.save_snapshot(snapshot)
    repository.save_candles(snapshot.dataset_snapshot_id, candles)
    return snapshot


def _build_candles(close_prices: list[float]):
    from crypto_backtest_workbench.domain.models import CanonicalCandle

    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []
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
                high=close_price + 1.0,
                low=close_price - 1.0,
                close=close_price,
                volume=100.0,
            )
        )
    return candles
