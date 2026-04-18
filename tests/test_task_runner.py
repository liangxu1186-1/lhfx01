from __future__ import annotations

from crypto_backtest_workbench.domain.models import FailureCode, TaskStatus
from crypto_backtest_workbench.jobs import (
    LocalTaskRunner,
    SingleRunTaskPayload,
    TaskExecutionError,
)


class SuccessfulExecutor:
    def __init__(self, runner: LocalTaskRunner, task_id: str) -> None:
        self.runner = runner
        self.task_id = task_id

    def execute_single_run(self, payload: SingleRunTaskPayload) -> dict[str, str]:
        task = self.runner.get_task(self.task_id)
        assert task.status is TaskStatus.RUNNING
        return {"run_id": payload.run_id}


class FailingExecutor:
    def execute_single_run(self, payload: SingleRunTaskPayload) -> None:
        raise TaskExecutionError(
            failure_code=FailureCode.CONFIG_INVALID,
            failure_stage="single_run_executor",
            failure_message=f"invalid config for {payload.run_id}",
        )


class CrashingExecutor:
    def execute_single_run(self, payload: SingleRunTaskPayload) -> None:
        raise RuntimeError(f"unexpected crash for {payload.run_id}")


def test_submit_single_run_creates_pending_task() -> None:
    runner = LocalTaskRunner()

    task = runner.submit_single_run(_payload(run_id="run-001"))

    assert task.task_id == "single-run:run-001"
    assert task.task_kind == "single_run"
    assert task.status is TaskStatus.PENDING
    assert runner.get_task(task.task_id) == task


def test_run_single_run_transitions_to_success_and_keeps_output() -> None:
    runner = LocalTaskRunner()
    task = runner.submit_single_run(_payload(run_id="run-002"))

    output = runner.run_single_run(task.task_id, SuccessfulExecutor(runner, task.task_id))
    updated = runner.get_task(task.task_id)

    assert output == {"run_id": "run-002"}
    assert updated.status is TaskStatus.SUCCESS
    assert updated.failure_code is None
    assert updated.updated_at >= task.updated_at
    assert runner.get_output(task.task_id) == {"run_id": "run-002"}


def test_run_single_run_records_structured_failure() -> None:
    runner = LocalTaskRunner()
    task = runner.submit_single_run(_payload(run_id="run-003"))

    output = runner.run_single_run(task.task_id, FailingExecutor())
    updated = runner.get_task(task.task_id)

    assert output is None
    assert updated.status is TaskStatus.FAILED
    assert updated.failure_code is FailureCode.CONFIG_INVALID
    assert updated.failure_stage == "single_run_executor"
    assert updated.failure_message == "invalid config for run-003"
    assert runner.get_output(task.task_id) is None


def test_run_single_run_maps_unhandled_exception_to_engine_runtime_error() -> None:
    runner = LocalTaskRunner()
    task = runner.submit_single_run(_payload(run_id="run-004"))

    output = runner.run_single_run(task.task_id, CrashingExecutor())
    updated = runner.get_task(task.task_id)

    assert output is None
    assert updated.status is TaskStatus.FAILED
    assert updated.failure_code is FailureCode.ENGINE_RUNTIME_ERROR
    assert updated.failure_stage == "task_runner"
    assert updated.failure_message == "unexpected crash for run-004"


def _payload(*, run_id: str) -> SingleRunTaskPayload:
    return SingleRunTaskPayload(
        run_id=run_id,
        dataset_snapshot_id="snapshot-001",
        feature_artifact_id="feature-001",
        strategy_name="ema_crossover",
        validation_split_id="split-001",
    )
