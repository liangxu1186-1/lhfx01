"""Task-backed application workflow for Phase 1 backtests."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.domain.models import FailureCode, TaskStatus
from crypto_backtest_workbench.jobs import (
    LocalTaskRunner,
    SingleRunTaskExecutor,
    SingleRunTaskPayload,
    TaskExecutionError,
    TaskRecord,
)
from crypto_backtest_workbench.storage.repositories import DatasetRepository, FeatureRepository, RunRepository

from .run_backtest import (
    DEFAULT_VALIDATION_SPLIT_ID,
    RunBacktestWorkflowRequest,
    RunBacktestWorkflowResult,
    run_backtest_workflow,
)


@dataclass(slots=True)
class RunBacktestTaskOutput:
    workflow_result: RunBacktestWorkflowResult
    persisted_paths: dict[str, object]


@dataclass(slots=True)
class RunBacktestTaskWorkflowResult:
    task: TaskRecord
    output: RunBacktestTaskOutput | None


class RunBacktestTaskExecutor(SingleRunTaskExecutor[RunBacktestTaskOutput]):
    """Bridge the application workflow into LocalTaskRunner."""

    def __init__(
        self,
        *,
        dataset_repository: DatasetRepository,
        feature_repository: FeatureRepository,
        run_repository: RunRepository,
        request: RunBacktestWorkflowRequest,
    ) -> None:
        self.dataset_repository = dataset_repository
        self.feature_repository = feature_repository
        self.run_repository = run_repository
        self.request = request

    def execute_single_run(self, payload: SingleRunTaskPayload) -> RunBacktestTaskOutput:
        if payload.run_id != self.request.run_id:
            raise TaskExecutionError(
                failure_code=FailureCode.CONFIG_INVALID,
                failure_stage="run_backtest_task_executor",
                failure_message=f"payload run_id {payload.run_id} does not match request {self.request.run_id}",
            )

        try:
            workflow_result = run_backtest_workflow(
                dataset_repository=self.dataset_repository,
                feature_repository=self.feature_repository,
                request=self.request,
            )
        except FileNotFoundError as exc:
            raise TaskExecutionError(
                failure_code=FailureCode.DATA_INVALID,
                failure_stage="run_backtest_task_executor",
                failure_message=str(exc),
            ) from exc
        except ValueError as exc:
            raise TaskExecutionError(
                failure_code=FailureCode.CONFIG_INVALID,
                failure_stage="run_backtest_task_executor",
                failure_message=str(exc),
            ) from exc

        persisted_paths = self.run_repository.save_single_run_result(workflow_result.single_run_result)
        return RunBacktestTaskOutput(
            workflow_result=workflow_result,
            persisted_paths=persisted_paths,
        )


def run_backtest_task_workflow(
    *,
    runner: LocalTaskRunner,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    run_repository: RunRepository,
    request: RunBacktestWorkflowRequest,
) -> RunBacktestTaskWorkflowResult:
    """Submit and execute a single-run backtest through LocalTaskRunner."""

    strategy_name = str(request.strategy_params.get("strategy_name") or request.strategy_params.get("name") or "ema_crossover")
    payload = SingleRunTaskPayload(
        run_id=request.run_id,
        dataset_snapshot_id=request.snapshot.dataset_snapshot_id,
        feature_artifact_id="pending",
        strategy_name=strategy_name,
        validation_split_id=(
            request.validation_split.validation_split_id
            if request.validation_split is not None
            else DEFAULT_VALIDATION_SPLIT_ID
        ),
    )
    task = runner.submit_single_run(payload)
    if task.status is TaskStatus.SUCCESS:
        output = runner.get_output(task.task_id)
        return RunBacktestTaskWorkflowResult(task=task, output=output)

    output = runner.run_single_run(
        task.task_id,
        RunBacktestTaskExecutor(
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
            request=request,
        ),
    )
    return RunBacktestTaskWorkflowResult(
        task=runner.get_task(task.task_id),
        output=output,
    )
