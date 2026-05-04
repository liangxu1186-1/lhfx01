from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.readmodels import (
    ParameterLabFilter,
    build_parameter_lab_rows,
    build_research_workflow,
    build_parameter_research_workspace,
    build_parameter_sensitivity_rows,
    filter_parameter_lab_rows,
    load_parameter_group_detail,
)
from crypto_backtest_workbench.app.workflows.run_backtest import (
    RunBacktestWorkflowRequest,
    run_backtest_workflow,
)
from crypto_backtest_workbench.domain.models import DatasetSnapshot, MarketType, PriceType, ResearchNote, ValidationSplit, ValidationTargetType
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileFeatureRepository,
    FileResearchNoteRepository,
    FileRunRepository,
)


def test_parameter_lab_rows_extract_strategy_and_execution_params(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    for run_id, fast_period, slow_period, leverage in [
        ("run-001", 2, 4, 2.0),
        ("run-002", 3, 6, 3.0),
    ]:
        workflow_result = run_backtest_workflow(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=snapshot,
                strategy_params={
                    "fast_period": fast_period,
                    "slow_period": slow_period,
                    "qty_policy_ref": "fixed_1",
                },
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=leverage,
                    fee_rate=0.001,
                    qty_by_policy={"fixed_1": 1.0},
                ),
                validation_split=ValidationSplit(
                    validation_split_id=f"split-{run_id}",
                    target_type=ValidationTargetType.DATASET_SNAPSHOT,
                    target_id=snapshot.dataset_snapshot_id,
                    warmup_bars=1,
                    is_start=snapshot.time_range_start + timedelta(hours=2),
                    is_end=snapshot.time_range_start + timedelta(hours=6),
                    oos_start=snapshot.time_range_start + timedelta(hours=6),
                    oos_end=snapshot.time_range_start + timedelta(hours=9),
                ),
                enable_buy_and_hold_benchmark=True,
            ),
        )
        run_repository.save_single_run_result(workflow_result.single_run_result)

    rows = build_parameter_lab_rows(run_repository)

    assert [row.run_id for row in rows] == ["run-002", "run-001"]
    assert rows[0].symbol == "BTC/USDT:USDT"
    assert rows[0].fast_period == 3
    assert rows[0].slow_period == 6
    assert rows[0].leverage == 3.0
    assert rows[0].max_drawdown >= 0
    assert rows[0].benchmark_return is not None
    assert rows[0].excess_return is not None
    assert rows[0].is_total_return is not None
    assert rows[0].oos_total_return is not None


def test_parameter_lab_rows_support_filter_and_sensitivity(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    for run_id, fast_period, slow_period in [
        ("run-101", 2, 4),
        ("run-102", 2, 5),
        ("run-103", 3, 5),
    ]:
        workflow_result = run_backtest_workflow(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=snapshot,
                strategy_params={
                    "fast_period": fast_period,
                    "slow_period": slow_period,
                    "qty_policy_ref": "fixed_1",
                },
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=2.0,
                    qty_by_policy={"fixed_1": 1.0},
                ),
                enable_buy_and_hold_benchmark=True,
            ),
        )
        run_repository.save_single_run_result(workflow_result.single_run_result)

    rows = build_parameter_lab_rows(run_repository)
    filtered_rows = filter_parameter_lab_rows(
        rows,
        parameter_filter=ParameterLabFilter(
            strategy_names=("ema_crossover",),
            validation_split_ids=("validation:none",),
            dataset_query="BTC/USDT",
            fast_period_range=(2, 2),
            slow_period_range=(4, 5),
            benchmark_mode="with",
        ),
    )
    sensitivity_rows = build_parameter_sensitivity_rows(
        filtered_rows,
        parameter_name="slow_period",
        metric_name="total_return",
    )

    assert [row.run_id for row in filtered_rows] == ["run-102", "run-101"]
    assert [row["slow_period"] for row in sensitivity_rows] == [4, 5]
    assert all(int(row["run_count"]) == 1 for row in sensitivity_rows)


def test_parameter_lab_rows_expose_risk_pct_of_equity_fields(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    workflow_result = run_backtest_workflow(
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        request=RunBacktestWorkflowRequest(
            run_id="run-risk-row",
            snapshot=snapshot,
            strategy_params={
                "strategy_name": "ema_pullback_atr_v2",
                "trend_fast_period": 8,
                "trend_slow_period": 34,
                "atr_entry_tolerance": 0.5,
                "atr_stop_mult": 1.5,
                "risk_reward_ratio": 2.0,
                "entry_ema_period": 21,
                "atr_period": 14,
                "min_atr_pct_of_price": 0.002,
                "min_stop_pct": 0.003,
                "qty_policy_ref": "risk_pct_of_equity",
                "risk_pct_per_trade": 0.01,
            },
            constraints=ExecutionConstraints(
                initial_cash=1_000.0,
                leverage=2.0,
                risk_pct_per_trade_by_policy={"risk_pct_of_equity": 0.01},
            ),
            enable_buy_and_hold_benchmark=True,
        ),
    )
    run_repository.save_single_run_result(workflow_result.single_run_result)

    row = next(item for item in build_parameter_lab_rows(run_repository) if item.run_id == "run-risk-row")
    assert row.qty_policy_ref == "risk_pct_of_equity"
    assert row.risk_pct_per_trade == 0.01
    assert "risk1%" in row.parameter_summary


def test_parameter_research_workspace_groups_by_subject_and_parameter_group(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    for run_id, fast_period in [("run-research-001", 2), ("run-research-002", 2), ("run-research-003", 3)]:
        workflow_result = run_backtest_workflow(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=snapshot,
                strategy_params={
                    "fast_period": fast_period,
                    "slow_period": 5,
                    "qty_policy_ref": "fixed_1",
                },
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=2.0,
                    qty_by_policy={"fixed_1": 1.0},
                ),
                validation_split=ValidationSplit(
                    validation_split_id="validation:research",
                    target_type=ValidationTargetType.DATASET_SNAPSHOT,
                    target_id=snapshot.dataset_snapshot_id,
                    warmup_bars=1,
                    is_start=snapshot.time_range_start + timedelta(hours=2),
                    is_end=snapshot.time_range_start + timedelta(hours=6),
                    oos_start=snapshot.time_range_start + timedelta(hours=6),
                    oos_end=snapshot.time_range_start + timedelta(hours=9),
                ),
                enable_buy_and_hold_benchmark=True,
            ),
        )
        run_repository.save_single_run_result(workflow_result.single_run_result)

    workspace = build_parameter_research_workspace(run_repository)

    assert len(workspace.subjects) == 1
    assert workspace.subjects[0].parameter_group_count == 2
    assert workspace.subjects[0].run_count == 3
    assert len(workspace.parameter_groups) == 2
    grouped = {group.fast_period: group for group in workspace.parameter_groups}
    assert grouped[2].run_count == 2
    assert grouped[3].run_count == 1
    assert grouped[2].neighbor_count == 1
    assert grouped[2].representative_run_id in {"run-research-001", "run-research-002"}


def test_parameter_group_detail_returns_runs_and_neighbors(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    for run_id, fast_period in [("run-detail-001", 2), ("run-detail-002", 3)]:
        workflow_result = run_backtest_workflow(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=snapshot,
                strategy_params={
                    "fast_period": fast_period,
                    "slow_period": 5,
                    "qty_policy_ref": "fixed_1",
                },
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=2.0,
                    qty_by_policy={"fixed_1": 1.0},
                ),
                enable_buy_and_hold_benchmark=True,
            ),
        )
        run_repository.save_single_run_result(workflow_result.single_run_result)

    workspace = build_parameter_research_workspace(run_repository)
    group = next(item for item in workspace.parameter_groups if item.fast_period == 2)
    detail = load_parameter_group_detail(run_repository, group_key=group.group_key)

    assert detail.group.group_key == group.group_key
    assert [run.run_id for run in detail.runs] == ["run-detail-001"]
    assert [neighbor.fast_period for neighbor in detail.neighbors] == [3]


def test_research_workflow_marks_risk_matrix_done_when_risk_variants_exist(tmp_path) -> None:
    dataset_repository = FileDatasetRepository(tmp_path)
    feature_repository = FileFeatureRepository(tmp_path)
    run_repository = FileRunRepository(tmp_path)
    note_repository = FileResearchNoteRepository(tmp_path)
    snapshot = _persist_snapshot(dataset_repository)

    for index, risk_pct in enumerate([0.05, 0.10]):
        run_id = f"run-risk-matrix-{risk_pct:g}".replace(".", "p")
        workflow_result = run_backtest_workflow(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=snapshot,
                strategy_params={
                    "strategy_name": "ema_pullback_atr_v2",
                    "entry_ema_period": 21,
                    "trend_fast_period": 2,
                    "trend_slow_period": 5,
                    "atr_period": 14,
                    "atr_entry_tolerance": 1.0,
                    "atr_stop_mult": 2.0,
                    "risk_reward_ratio": 2.0,
                    "qty_policy_ref": "risk_pct_of_equity",
                    "risk_pct_per_trade": risk_pct,
                },
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=10.0,
                    fee_rate=0.001,
                    risk_pct_per_trade_by_policy={"risk_pct_of_equity": risk_pct},
                ),
                enable_buy_and_hold_benchmark=True,
            ),
        )
        workflow_result.single_run_result.run.validation_split_id = f"validation:risk-matrix-{index}"
        run_repository.save_single_run_result(workflow_result.single_run_result)

    workspace = build_parameter_research_workspace(run_repository)
    assert {group.risk_matrix_count for group in workspace.parameter_groups} == {2}
    group = workspace.parameter_groups[0]
    note_repository.save_note(
        ResearchNote(
            note_id="note-risk-matrix-pool",
            target_type="parameter_group",
            target_id=group.group_key,
            content="加入研究池",
            author="test",
            labels=("research_pool",),
        )
    )

    workflow = build_research_workflow(run_repository, note_repository)

    candidate = workflow.research_pool["candidates"][0]
    assert candidate["risk_matrix_summary"]["status"] == "已跑"
    assert candidate["risk_matrix_summary"]["group_count"] == 2


def _persist_snapshot(repository: FileDatasetRepository) -> DatasetSnapshot:
    candles = _build_candles([100.0, 99.0, 101.0, 104.0, 102.0, 106.0, 108.0, 105.0, 109.0, 111.0])
    snapshot = DatasetSnapshot(
        dataset_snapshot_id="snapshot-parameter-lab",
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
        storage_uri="datasets/snapshot-parameter-lab",
        data_source="ccxt_rest",
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
