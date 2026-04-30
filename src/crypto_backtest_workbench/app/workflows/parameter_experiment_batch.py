"""Task-backed multi-snapshot parameter experiment batch workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from crypto_backtest_workbench.app.workflows.parameter_experiment_task import (
    DEFAULT_BASE_CONFIG_URI,
    DEFAULT_BENCHMARK_POLICY_VERSION,
    ParameterExperimentTaskRequest,
    build_parameter_experiment_task,
    run_parameter_experiment_task_workflow,
)
from crypto_backtest_workbench.domain.models import (
    ExperimentBatch,
    FailureCode,
    SearchType,
    SeedPolicy,
    TaskStatus,
)
from crypto_backtest_workbench.jobs.task_models import TaskRecord
from crypto_backtest_workbench.storage.repositories import (
    DatasetRepository,
    ExperimentBatchRepository,
    FeatureRepository,
    ParameterExperimentRepository,
    RunRepository,
    TaskRepository,
)


@dataclass(slots=True)
class ParameterExperimentBatchRequest:
    batch_id: str
    snapshots: tuple[object, ...]
    search_type: SearchType
    fast_periods: tuple[int, ...]
    slow_periods: tuple[int, ...]
    qty_policy_ref: str
    qty: float | None
    initial_cash: float
    leverage_candidates: tuple[float, ...]
    fee_rate: float
    slippage_bps: float
    min_notional: float
    cash_allocation_pct: float | None = None
    benchmark_enabled: bool = True
    max_samples: int | None = None
    seed: int | None = None
    validation_split: object | None = None
    validation_split_factory: object | None = None


@dataclass(slots=True)
class ParameterExperimentBatchWorkflowResult:
    task: TaskRecord
    batch: ExperimentBatch
    experiment_ids: list[str]
    run_ids: list[str]


def build_parameter_experiment_batch(
    request: ParameterExperimentBatchRequest,
) -> tuple[TaskRecord, ExperimentBatch, list[ParameterExperimentTaskRequest], int]:
    if not request.batch_id.strip():
        raise ValueError("batch_id must not be empty")
    if not request.snapshots:
        raise ValueError("Parameter experiment batch requires at least one snapshot")
    snapshot_ids = [str(getattr(snapshot, "dataset_snapshot_id", "")).strip() for snapshot in request.snapshots]
    if any(not snapshot_id for snapshot_id in snapshot_ids):
        raise ValueError("All batch snapshots must have dataset_snapshot_id")
    if len(set(snapshot_ids)) != len(snapshot_ids):
        raise ValueError("Batch snapshots must not contain duplicates")

    child_requests: list[ParameterExperimentTaskRequest] = []
    experiment_ids: list[str] = []
    planned_run_count = 0
    for index, snapshot in enumerate(request.snapshots, start=1):
        validation_split = _validation_split_for_snapshot(request=request, snapshot=snapshot)
        experiment_id = _batch_experiment_id(
            batch_id=request.batch_id,
            snapshot_id=str(getattr(snapshot, "dataset_snapshot_id", "")),
            index=index,
        )
        child_request = ParameterExperimentTaskRequest(
            experiment_id=experiment_id,
            snapshot=snapshot,
            search_type=request.search_type,
            fast_periods=request.fast_periods,
            slow_periods=request.slow_periods,
            qty_policy_ref=request.qty_policy_ref,
            qty=request.qty,
            initial_cash=request.initial_cash,
            leverage_candidates=request.leverage_candidates,
            fee_rate=request.fee_rate,
            slippage_bps=request.slippage_bps,
            min_notional=request.min_notional,
            cash_allocation_pct=request.cash_allocation_pct,
            benchmark_enabled=request.benchmark_enabled,
            max_samples=request.max_samples,
            seed=request.seed,
            validation_split=validation_split,
        )
        _, experiment, combinations = build_parameter_experiment_task(child_request)
        child_requests.append(child_request)
        experiment_ids.append(experiment.experiment_id)
        planned_run_count += len(combinations)

    task = TaskRecord(
        task_id=f"parameter-experiment-batch:{request.batch_id}",
        task_kind="parameter_experiment_batch",
        status=TaskStatus.PENDING,
    )
    batch = ExperimentBatch(
        batch_id=request.batch_id,
        strategy_name="ema_crossover",
        dataset_snapshot_ids=tuple(snapshot_ids),
        validation_split_id=_batch_validation_split_id(request),
        metric_policy_id="metrics_daily_365_v1",
        benchmark_policy_version=DEFAULT_BENCHMARK_POLICY_VERSION,
        search_type=request.search_type,
        search_space_json={
            "fast_periods": list(request.fast_periods),
            "slow_periods": list(request.slow_periods),
            "leverage_candidates": list(request.leverage_candidates),
            "snapshot_count": len(request.snapshots),
            "combination_count_per_snapshot": planned_run_count // len(request.snapshots),
            "planned_run_count": planned_run_count,
            "max_samples": request.max_samples,
        },
        base_config_uri=DEFAULT_BASE_CONFIG_URI,
        seed_policy=SeedPolicy.FIXED if request.seed is not None else SeedPolicy.GLOBAL_RANDOM,
        seed=request.seed,
        experiment_ids=tuple(experiment_ids),
    )
    return task, batch, child_requests, planned_run_count


def _validation_split_for_snapshot(*, request: ParameterExperimentBatchRequest, snapshot: object) -> object | None:
    if request.validation_split_factory is not None:
        factory = request.validation_split_factory
        if not callable(factory):
            raise ValueError("validation_split_factory must be callable")
        return factory(snapshot)
    return request.validation_split


def _batch_validation_split_id(request: ParameterExperimentBatchRequest) -> str:
    if request.validation_split_factory is not None:
        return f"validation:{request.batch_id}:per-snapshot"
    if request.validation_split is not None:
        return str(getattr(request.validation_split, "validation_split_id", "validation:batch"))
    return "validation:none"


def run_parameter_experiment_batch_workflow(
    *,
    request: ParameterExperimentBatchRequest,
    task_repository: TaskRepository,
    batch_repository: ExperimentBatchRepository,
    experiment_repository: ParameterExperimentRepository,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    run_repository: RunRepository,
) -> ParameterExperimentBatchWorkflowResult:
    task, batch, child_requests, planned_run_count = build_parameter_experiment_batch(request)
    task_repository.save_task(task)
    batch_repository.save_batch(batch)
    batch_repository.save_execution_index(
        batch.batch_id,
        {
            "batch_id": batch.batch_id,
            "task_id": task.task_id,
            "status": task.status.value,
            "dataset_snapshot_ids": list(batch.dataset_snapshot_ids),
            "experiment_ids": list(batch.experiment_ids),
            "run_ids": [],
            "child_task_ids": [],
            "failed_experiment_ids": [],
            "planned_experiment_count": len(batch.experiment_ids),
            "planned_run_count": planned_run_count,
            "updated_at": task.updated_at.isoformat(),
        },
    )

    running_task = _transition_task(task, status=TaskStatus.RUNNING)
    task_repository.save_task(running_task)

    run_ids: list[str] = []
    child_task_ids: list[str] = []
    failed_experiment_ids: list[str] = []
    for child_request in child_requests:
        child_result = run_parameter_experiment_task_workflow(
            request=child_request,
            task_repository=task_repository,
            experiment_repository=experiment_repository,
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
        )
        run_ids.extend(child_result.run_ids)
        child_task_ids.append(child_result.task.task_id)
        if child_result.task.status is TaskStatus.FAILED:
            failed_experiment_ids.append(child_request.experiment_id)
        batch_repository.save_execution_index(
            batch.batch_id,
            {
                "batch_id": batch.batch_id,
                "task_id": running_task.task_id,
                "status": TaskStatus.RUNNING.value,
                "dataset_snapshot_ids": list(batch.dataset_snapshot_ids),
                "experiment_ids": list(batch.experiment_ids),
                "run_ids": run_ids,
                "child_task_ids": child_task_ids,
                "failed_experiment_ids": failed_experiment_ids,
                "planned_experiment_count": len(batch.experiment_ids),
                "planned_run_count": planned_run_count,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    if failed_experiment_ids:
        final_task = _transition_task(
            running_task,
            status=TaskStatus.FAILED,
            failure_code=FailureCode.ENGINE_RUNTIME_ERROR,
            failure_stage="parameter_experiment_batch_workflow",
            failure_message=f"{len(failed_experiment_ids)} child experiment(s) failed",
        )
    else:
        final_task = _transition_task(running_task, status=TaskStatus.SUCCESS)
    task_repository.save_task(final_task)
    batch_repository.save_execution_index(
        batch.batch_id,
        {
            "batch_id": batch.batch_id,
            "task_id": final_task.task_id,
            "status": final_task.status.value,
            "dataset_snapshot_ids": list(batch.dataset_snapshot_ids),
            "experiment_ids": list(batch.experiment_ids),
            "run_ids": run_ids,
            "child_task_ids": child_task_ids,
            "failed_experiment_ids": failed_experiment_ids,
            "planned_experiment_count": len(batch.experiment_ids),
            "planned_run_count": planned_run_count,
            "updated_at": final_task.updated_at.isoformat(),
        },
    )
    return ParameterExperimentBatchWorkflowResult(
        task=final_task,
        batch=batch,
        experiment_ids=list(batch.experiment_ids),
        run_ids=run_ids,
    )


def _batch_experiment_id(*, batch_id: str, snapshot_id: str, index: int) -> str:
    suffix = snapshot_id.split("-")[-1][:8] if snapshot_id else f"{index:02d}"
    return f"{batch_id}-exp-{index:02d}-{suffix}"


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
