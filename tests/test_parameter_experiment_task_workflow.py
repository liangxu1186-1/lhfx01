from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.workflows import (
    ParameterExperimentTaskRequest,
    run_parameter_experiment_task_workflow,
)
from crypto_backtest_workbench.domain.models import DatasetSnapshot, MarketType, PriceType, SearchType, TaskStatus
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileFeatureRepository,
    FileParameterExperimentRepository,
    FileRunRepository,
    FileTaskRepository,
)


def test_parameter_experiment_task_workflow_persists_parent_and_child_tasks(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    result = run_parameter_experiment_task_workflow(
        request=ParameterExperimentTaskRequest(
            experiment_id="experiment-001",
            snapshot=snapshot,
            search_type=SearchType.GRID,
            fast_periods=(2, 3),
            slow_periods=(4, 5),
            qty_policy_ref="fixed_1",
            qty=0.01,
            initial_cash=1000.0,
            leverage_candidates=(1.0, 2.0),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    execution = experiment_repository.load_execution_index("experiment-001")

    assert result.task.task_id == "parameter-experiment:experiment-001"
    assert result.task.status is TaskStatus.SUCCESS
    assert len(result.run_ids) == 8
    assert len(result.child_task_ids) == 8
    assert execution["status"] == "success"
    assert len(execution["run_ids"]) == 8
    assert len(run_repository.list_run_ids()) == 8
    assert any(run_id.endswith("-l2") for run_id in result.run_ids)
    assert task_repository.load_task("parameter-experiment:experiment-001").status is TaskStatus.SUCCESS


def test_parameter_experiment_task_workflow_rejects_invalid_parameter_grid(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    try:
        run_parameter_experiment_task_workflow(
            request=ParameterExperimentTaskRequest(
                experiment_id="experiment-invalid",
                snapshot=snapshot,
                search_type=SearchType.GRID,
                fast_periods=(5, 8),
                slow_periods=(5, 13),
                qty_policy_ref="fixed_1",
                qty=0.01,
                initial_cash=1000.0,
                leverage_candidates=(1.0,),
                fee_rate=0.0,
                slippage_bps=0.0,
                min_notional=0.0,
            ),
            task_repository=task_repository,
            experiment_repository=experiment_repository,
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
        )
        raise AssertionError("Expected invalid parameter grid to raise ValueError")
    except ValueError as exc:
        assert "fast_period < slow_period" in str(exc)


def test_parameter_experiment_task_workflow_supports_percent_of_cash_sizing(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    result = run_parameter_experiment_task_workflow(
        request=ParameterExperimentTaskRequest(
            experiment_id="experiment-cash-001",
            snapshot=snapshot,
            search_type=SearchType.GRID,
            fast_periods=(2,),
            slow_periods=(4,),
            qty_policy_ref="percent_of_cash",
            qty=None,
            cash_allocation_pct=75.0,
            initial_cash=1000.0,
            leverage_candidates=(2.0,),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    run_id = result.run_ids[0]
    manifest = run_repository.load_manifest(run_id)
    constraints = manifest.resolved_config_json["execution_constraints"]
    assert constraints["cash_allocation_pct_by_policy"] == {"percent_of_cash": 75.0}


def test_parameter_experiment_task_workflow_builds_v2_combinations(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    result = run_parameter_experiment_task_workflow(
        request=ParameterExperimentTaskRequest(
            experiment_id="experiment-v2-001",
            snapshot=snapshot,
            search_type=SearchType.GRID,
            strategy_name="ema_pullback_atr_v2",
            strategy_version="v2",
            trend_fast_periods=(8, 13),
            trend_slow_periods=(34,),
            atr_entry_tolerances=(0.5, 1.0),
            atr_stop_mults=(1.5,),
            risk_reward_ratios=(2.0,),
            qty_policy_ref="percent_of_cash",
            qty=None,
            cash_allocation_pct=50.0,
            initial_cash=1000.0,
            leverage_candidates=(1.0, 2.0),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    assert len(result.run_ids) == 8
    assert any("-tf8-ts34-tol0p5-sl1p5-rr2-l2" in run_id for run_id in result.run_ids)
    manifest = run_repository.load_manifest(result.run_ids[0])
    params = manifest.resolved_config_json["strategy_params"]
    assert params["entry_ema_period"] == 21
    assert params["atr_period"] == 14
    assert params["min_atr_pct_of_price"] == 0.002
    assert params["min_stop_pct"] == 0.003


def test_parameter_experiment_task_workflow_supports_v2_risk_pct_of_equity(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    result = run_parameter_experiment_task_workflow(
        request=ParameterExperimentTaskRequest(
            experiment_id="experiment-v2-risk-001",
            snapshot=snapshot,
            search_type=SearchType.GRID,
            strategy_name="ema_pullback_atr_v2",
            strategy_version="v2",
            trend_fast_periods=(8,),
            trend_slow_periods=(34,),
            atr_entry_tolerances=(0.5,),
            atr_stop_mults=(1.5,),
            risk_reward_ratios=(2.0,),
            qty_policy_ref="risk_pct_of_equity",
            qty=None,
            risk_pct_per_trade=0.01,
            initial_cash=1000.0,
            leverage_candidates=(1.0,),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    manifest = run_repository.load_manifest(result.run_ids[0])
    constraints = manifest.resolved_config_json["execution_constraints"]
    params = manifest.resolved_config_json["strategy_params"]
    assert constraints["risk_pct_per_trade_by_policy"] == {"risk_pct_of_equity": 0.01}
    assert params["risk_pct_per_trade"] == 0.01


def test_parameter_experiment_task_workflow_supports_v2_risk_pct_of_cash_allocation(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    task_repository = FileTaskRepository(tmp_path)
    experiment_repository = FileParameterExperimentRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    result = run_parameter_experiment_task_workflow(
        request=ParameterExperimentTaskRequest(
            experiment_id="experiment-v2-allocated-risk-001",
            snapshot=snapshot,
            search_type=SearchType.GRID,
            strategy_name="ema_pullback_atr_v2",
            strategy_version="v2",
            trend_fast_periods=(8,),
            trend_slow_periods=(34,),
            atr_entry_tolerances=(0.5,),
            atr_stop_mults=(1.5,),
            risk_reward_ratios=(2.0,),
            qty_policy_ref="risk_pct_of_cash_allocation",
            qty=None,
            cash_allocation_pct=50.0,
            risk_pct_per_trade=0.01,
            initial_cash=1000.0,
            leverage_candidates=(1.0,),
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        ),
        task_repository=task_repository,
        experiment_repository=experiment_repository,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
    )

    manifest = run_repository.load_manifest(result.run_ids[0])
    constraints = manifest.resolved_config_json["execution_constraints"]
    params = manifest.resolved_config_json["strategy_params"]
    assert constraints["cash_allocation_pct_by_policy"] == {"risk_pct_of_cash_allocation": 50.0}
    assert constraints["risk_pct_per_trade_by_policy"] == {"risk_pct_of_cash_allocation": 0.01}
    assert params["cash_allocation_pct"] == 50.0
    assert params["risk_pct_per_trade"] == 0.01


def _persist_snapshot(repository: FileDatasetRepository) -> DatasetSnapshot:
    candles = _build_candles([100.0, 99.0, 101.0, 104.0, 102.0, 106.0, 108.0, 105.0, 109.0, 111.0])
    snapshot = DatasetSnapshot(
        dataset_snapshot_id="snapshot-parameter-experiment",
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
        storage_uri="datasets/snapshot-parameter-experiment",
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
