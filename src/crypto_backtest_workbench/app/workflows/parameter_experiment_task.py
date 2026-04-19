"""Task-backed parameter experiment workflow for EMA strategy."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product

from crypto_backtest_workbench.app.workflows.run_backtest import RunBacktestWorkflowRequest
from crypto_backtest_workbench.app.workflows.run_backtest_task import run_backtest_task_workflow
from crypto_backtest_workbench.domain.models import (
    FailureCode,
    ParameterExperiment,
    SearchType,
    SeedPolicy,
    TaskStatus,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.jobs.task_models import TaskRecord
from crypto_backtest_workbench.storage.repositories import (
    DatasetRepository,
    FeatureRepository,
    ParameterExperimentRepository,
    RunRepository,
    TaskRepository,
)


DEFAULT_BENCHMARK_POLICY_VERSION = "buy_and_hold_v1"
DEFAULT_BASE_CONFIG_URI = "memory://parameter-experiments/base-config.json"
DEFAULT_BENCHMARK_CONFIG_URI = "memory://parameter-experiments/benchmark-config.json"


@dataclass(slots=True)
class ParameterExperimentTaskRequest:
    experiment_id: str
    snapshot: object
    search_type: SearchType
    fast_periods: tuple[int, ...]
    slow_periods: tuple[int, ...]
    qty_policy_ref: str
    qty: float | None
    initial_cash: float
    leverage: float
    fee_rate: float
    slippage_bps: float
    min_notional: float
    cash_allocation_pct: float | None = None
    benchmark_enabled: bool = True
    max_samples: int | None = None
    seed: int | None = None
    validation_split: object | None = None


@dataclass(slots=True)
class ParameterExperimentTaskWorkflowResult:
    task: TaskRecord
    experiment: ParameterExperiment
    run_ids: list[str]
    child_task_ids: list[str]


def build_parameter_experiment_task(
    request: ParameterExperimentTaskRequest,
) -> tuple[TaskRecord, ParameterExperiment, list[dict[str, int]]]:
    _validate_parameter_experiment_request(request)
    combinations = _build_parameter_combinations(request)
    task = TaskRecord(
        task_id=f"parameter-experiment:{request.experiment_id}",
        task_kind="parameter_experiment",
        status=TaskStatus.PENDING,
    )
    search_space = {
        "fast_periods": list(request.fast_periods),
        "slow_periods": list(request.slow_periods),
        "combination_count": len(combinations),
        "max_samples": request.max_samples,
    }
    experiment = ParameterExperiment(
        experiment_id=request.experiment_id,
        strategy_name="ema_crossover",
        dataset_bundle_id=str(getattr(request.snapshot, "dataset_snapshot_id", "")),
        validation_split_id=(
            getattr(request.validation_split, "validation_split_id", "validation:none")
            if request.validation_split is not None
            else "validation:none"
        ),
        metric_policy_id="metrics_daily_365_v1",
        benchmark_policy_version=DEFAULT_BENCHMARK_POLICY_VERSION,
        benchmark_config_uri=DEFAULT_BENCHMARK_CONFIG_URI,
        search_type=request.search_type,
        search_space_json=search_space,
        base_config_uri=DEFAULT_BASE_CONFIG_URI,
        seed_policy=SeedPolicy.FIXED if request.seed is not None else SeedPolicy.GLOBAL_RANDOM,
        seed=request.seed,
    )
    return task, experiment, combinations


def run_parameter_experiment_task_workflow(
    *,
    request: ParameterExperimentTaskRequest,
    task_repository: TaskRepository,
    experiment_repository: ParameterExperimentRepository,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    run_repository: RunRepository,
) -> ParameterExperimentTaskWorkflowResult:
    task, experiment, combinations = build_parameter_experiment_task(request)
    task_repository.save_task(task)
    experiment_repository.save_experiment(experiment)

    running_task = _transition_task(task, status=TaskStatus.RUNNING)
    task_repository.save_task(running_task)

    run_ids: list[str] = []
    child_task_ids: list[str] = []
    failed_child_task_ids: list[str] = []
    for index, params in enumerate(combinations, start=1):
        run_id = _experiment_run_id(
            experiment_id=request.experiment_id,
            fast_period=params["fast_period"],
            slow_period=params["slow_period"],
            index=index,
        )
        run_ids.append(run_id)
        child_result = run_backtest_task_workflow(
            runner=LocalTaskRunner(),
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=request.snapshot,
                strategy_params={
                    "fast_period": params["fast_period"],
                    "slow_period": params["slow_period"],
                    "qty_policy_ref": request.qty_policy_ref,
                },
                constraints=ExecutionConstraints(
                    initial_cash=request.initial_cash,
                    leverage=request.leverage,
                    fee_rate=request.fee_rate,
                    slippage_bps=request.slippage_bps,
                    min_notional=request.min_notional,
                    qty_by_policy={request.qty_policy_ref: request.qty} if request.qty is not None else {},
                    cash_allocation_pct_by_policy=(
                        {request.qty_policy_ref: request.cash_allocation_pct}
                        if request.cash_allocation_pct is not None
                        else {}
                    ),
                ),
                validation_split=request.validation_split,
                enable_buy_and_hold_benchmark=request.benchmark_enabled,
                seed=request.seed,
            ),
        )
        child_task_ids.append(child_result.task.task_id)
        task_repository.save_task(child_result.task)
        if child_result.output is None or child_result.task.status is TaskStatus.FAILED:
            failed_child_task_ids.append(child_result.task.task_id)

        experiment_repository.save_execution_index(
            request.experiment_id,
            {
                "experiment_id": request.experiment_id,
                "task_id": running_task.task_id,
                "status": TaskStatus.RUNNING.value,
                "run_ids": run_ids,
                "child_task_ids": child_task_ids,
                "failed_child_task_ids": failed_child_task_ids,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    if failed_child_task_ids:
        final_task = _transition_task(
            running_task,
            status=TaskStatus.FAILED,
            failure_code=FailureCode.ENGINE_RUNTIME_ERROR,
            failure_stage="parameter_experiment_task_workflow",
            failure_message=f"{len(failed_child_task_ids)} child run task(s) failed",
        )
    else:
        final_task = _transition_task(
            running_task,
            status=TaskStatus.SUCCESS,
        )
    task_repository.save_task(final_task)
    experiment_repository.save_execution_index(
        request.experiment_id,
        {
            "experiment_id": request.experiment_id,
            "task_id": final_task.task_id,
            "status": final_task.status.value,
            "run_ids": run_ids,
            "child_task_ids": child_task_ids,
            "failed_child_task_ids": failed_child_task_ids,
            "updated_at": final_task.updated_at.isoformat(),
        },
    )
    return ParameterExperimentTaskWorkflowResult(
        task=final_task,
        experiment=experiment,
        run_ids=run_ids,
        child_task_ids=child_task_ids,
    )


def _build_parameter_combinations(request: ParameterExperimentTaskRequest) -> list[dict[str, int]]:
    combinations = [
        {"fast_period": fast_period, "slow_period": slow_period}
        for fast_period, slow_period in product(request.fast_periods, request.slow_periods)
    ]
    if not combinations:
        raise ValueError("Parameter experiment requires at least one parameter combination")

    if request.search_type is SearchType.GRID:
        return combinations

    sample_size = request.max_samples or len(combinations)
    if sample_size <= 0:
        raise ValueError("max_samples must be positive")
    rng = random.Random(request.seed)
    sample_size = min(sample_size, len(combinations))
    return rng.sample(combinations, sample_size)


def _validate_parameter_experiment_request(request: ParameterExperimentTaskRequest) -> None:
    if not request.experiment_id.strip():
        raise ValueError("experiment_id must not be empty")
    if request.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if request.leverage <= 0:
        raise ValueError("leverage must be positive")
    if request.fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")
    if request.slippage_bps < 0:
        raise ValueError("slippage_bps must be >= 0")
    if request.min_notional < 0:
        raise ValueError("min_notional must be >= 0")
    if request.qty_policy_ref == "percent_of_cash":
        if request.cash_allocation_pct is None:
            raise ValueError("cash_allocation_pct must be provided for percent_of_cash")
        if request.cash_allocation_pct <= 0 or request.cash_allocation_pct > 100:
            raise ValueError("cash_allocation_pct must be in (0, 100]")
    else:
        if request.qty is None or request.qty <= 0:
            raise ValueError("qty must be positive")
    _validate_periods(request.fast_periods, field_name="fast_periods")
    _validate_periods(request.slow_periods, field_name="slow_periods")
    if request.search_type is SearchType.GRID and request.max_samples is not None:
        raise ValueError("max_samples is only supported for random search")
    if request.search_type is SearchType.RANDOM and request.max_samples is not None and request.max_samples <= 0:
        raise ValueError("max_samples must be positive")

    invalid_pairs = [
        (fast_period, slow_period)
        for fast_period, slow_period in product(request.fast_periods, request.slow_periods)
        if fast_period >= slow_period
    ]
    if invalid_pairs:
        examples = ", ".join(f"{fast}/{slow}" for fast, slow in invalid_pairs[:5])
        raise ValueError(f"All parameter combinations must satisfy fast_period < slow_period, invalid pairs: {examples}")


def _validate_periods(periods: tuple[int, ...], *, field_name: str) -> None:
    if not periods:
        raise ValueError(f"{field_name} must not be empty")
    if any(period <= 0 for period in periods):
        raise ValueError(f"{field_name} must contain only positive integers")
    if len(set(periods)) != len(periods):
        raise ValueError(f"{field_name} must not contain duplicate values")


def _experiment_run_id(*, experiment_id: str, fast_period: int, slow_period: int, index: int) -> str:
    return f"{experiment_id}-run-{index:03d}-f{fast_period}-s{slow_period}"


def _transition_task(
    task: TaskRecord,
    *,
    status: TaskStatus,
    failure_code: FailureCode | None = None,
    failure_stage: str | None = None,
    failure_message: str | None = None,
) -> TaskRecord:
    return TaskRecord(
        task_id=task.task_id,
        task_kind=task.task_kind,
        status=status,
        created_at=task.created_at,
        updated_at=datetime.now(UTC),
        failure_code=failure_code,
        failure_stage=failure_stage,
        failure_message=failure_message,
    )
