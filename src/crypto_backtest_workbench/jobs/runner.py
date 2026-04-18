"""Local synchronous task runner for Phase 1 jobs."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, TypeVar

from crypto_backtest_workbench.domain.models import FailureCode, TaskStatus, now_utc
from crypto_backtest_workbench.jobs.task_models import SingleRunTaskPayload, TaskRecord

TaskOutputT = TypeVar("TaskOutputT")


class SingleRunTaskExecutor(Protocol[TaskOutputT]):
    """Execution protocol for single-run tasks."""

    def execute_single_run(self, payload: SingleRunTaskPayload) -> TaskOutputT:
        """Execute a submitted single-run payload."""


class TaskExecutionError(RuntimeError):
    """Structured task failure used to populate TaskRecord fields."""

    def __init__(
        self,
        *,
        failure_code: FailureCode,
        failure_stage: str,
        failure_message: str,
    ) -> None:
        super().__init__(failure_message)
        self.failure_code = failure_code
        self.failure_stage = failure_stage
        self.failure_message = failure_message


class LocalTaskRunner:
    """Minimal in-process runner that executes submitted tasks synchronously."""

    def __init__(self) -> None:
        self._task_records: dict[str, TaskRecord] = {}
        self._single_run_payloads: dict[str, SingleRunTaskPayload] = {}
        self._task_outputs: dict[str, object] = {}

    def submit_single_run(self, payload: SingleRunTaskPayload) -> TaskRecord:
        task_id = _single_run_task_id(payload)
        existing = self._task_records.get(task_id)
        if existing is not None:
            return existing

        record = TaskRecord(
            task_id=task_id,
            task_kind="single_run",
            status=TaskStatus.PENDING,
        )
        self._task_records[task_id] = record
        self._single_run_payloads[task_id] = payload
        return record

    def get_task(self, task_id: str) -> TaskRecord:
        return self._task_records[task_id]

    def get_output(self, task_id: str) -> object | None:
        return self._task_outputs.get(task_id)

    def run_single_run(
        self,
        task_id: str,
        executor: SingleRunTaskExecutor[TaskOutputT],
    ) -> TaskOutputT | None:
        record = self._task_records[task_id]
        payload = self._single_run_payloads[task_id]
        self._task_records[task_id] = _transition(record, status=TaskStatus.RUNNING)

        try:
            output = executor.execute_single_run(payload)
        except TaskExecutionError as error:
            self._task_records[task_id] = _transition(
                self._task_records[task_id],
                status=TaskStatus.FAILED,
                failure_code=error.failure_code,
                failure_stage=error.failure_stage,
                failure_message=error.failure_message,
            )
            return None
        except Exception as error:  # pragma: no cover - defensive fallback
            self._task_records[task_id] = _transition(
                self._task_records[task_id],
                status=TaskStatus.FAILED,
                failure_code=FailureCode.ENGINE_RUNTIME_ERROR,
                failure_stage="task_runner",
                failure_message=str(error),
            )
            return None

        self._task_outputs[task_id] = output
        self._task_records[task_id] = _transition(
            self._task_records[task_id],
            status=TaskStatus.SUCCESS,
            failure_code=None,
            failure_stage=None,
            failure_message=None,
        )
        return output


def _single_run_task_id(payload: SingleRunTaskPayload) -> str:
    return f"single-run:{payload.run_id}"


def _transition(
    record: TaskRecord,
    *,
    status: TaskStatus,
    failure_code: FailureCode | None = None,
    failure_stage: str | None = None,
    failure_message: str | None = None,
) -> TaskRecord:
    return replace(
        record,
        status=status,
        updated_at=now_utc(),
        failure_code=failure_code,
        failure_stage=failure_stage,
        failure_message=failure_message,
    )
