from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.workflows import (
    ParameterExperimentBatchRequest,
    run_parameter_experiment_batch_workflow,
)
from crypto_backtest_workbench.domain.models import DatasetSnapshot, MarketType, PriceType, SearchType, TaskStatus
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileExperimentBatchRepository,
    FileFeatureRepository,
    FileParameterExperimentRepository,
    FileRunRepository,
    FileTaskRepository,
)


def test_parameter_experiment_batch_workflow_fans_out_into_multiple_experiments(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    batch_repository = FileExperimentBatchRepository(tmp_path)
    snapshots = (
        _persist_snapshot(dataset_repository, snapshot_id="snapshot-batch-001", timeframe="1h"),
        _persist_snapshot(dataset_repository, snapshot_id="snapshot-batch-002", timeframe="4h"),
    )

    result = run_parameter_experiment_batch_workflow(
        request=ParameterExperimentBatchRequest(
            batch_id="batch-001",
            snapshots=snapshots,
            search_type=SearchType.GRID,
            fast_periods=(2, 3),
            slow_periods=(5,),
            qty_policy_ref="percent_of_cash",
            qty=None,
            cash_allocation_pct=100.0,
            initial_cash=1000.0,
            leverage_candidates=(1.0, 2.0),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        batch_repository=batch_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    execution = batch_repository.load_execution_index("batch-001")

    assert result.task.task_id == "parameter-experiment-batch:batch-001"
    assert result.task.status is TaskStatus.SUCCESS
    assert len(result.experiment_ids) == 2
    assert len(result.run_ids) == 8
    assert execution["status"] == "success"
    assert execution["planned_experiment_count"] == 2
    assert execution["planned_run_count"] == 8
    assert len(execution["experiment_ids"]) == 2
    assert len(run_repository.list_run_ids()) == 8
    batch = batch_repository.load_batch("batch-001")
    assert batch.search_space_json["leverage_candidates"] == [1.0, 2.0]


def test_parameter_experiment_batch_workflow_rejects_duplicate_snapshots(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    batch_repository = FileExperimentBatchRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository, snapshot_id="snapshot-batch-duplicate", timeframe="1h")

    try:
        run_parameter_experiment_batch_workflow(
            request=ParameterExperimentBatchRequest(
                batch_id="batch-duplicate",
                snapshots=(snapshot, snapshot),
                search_type=SearchType.GRID,
                fast_periods=(2,),
                slow_periods=(5,),
                qty_policy_ref="percent_of_cash",
                qty=None,
                cash_allocation_pct=100.0,
                initial_cash=1000.0,
                leverage_candidates=(1.0,),
                fee_rate=0.0,
                slippage_bps=0.0,
                min_notional=0.0,
            ),
            task_repository=task_repository,
            batch_repository=batch_repository,
            experiment_repository=experiment_repository,
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
        )
        raise AssertionError("Expected duplicate snapshots to raise ValueError")
    except ValueError as exc:
        assert "duplicates" in str(exc)


def _persist_snapshot(repository: FileDatasetRepository, *, snapshot_id: str, timeframe: str) -> DatasetSnapshot:
    candles = _build_candles([100.0, 99.0, 101.0, 104.0, 102.0, 106.0, 108.0, 105.0, 109.0, 111.0], timeframe=timeframe)
    snapshot = DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source="binance",
        exchange="binance",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe=timeframe,
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


def _build_candles(close_prices: list[float], *, timeframe: str):
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
                timeframe=timeframe,
                open=close_price,
                high=close_price + 1.0,
                low=close_price - 1.0,
                close=close_price,
                volume=100.0,
            )
        )
    return candles
