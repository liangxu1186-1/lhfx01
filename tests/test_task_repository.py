from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import FailureCode, TaskStatus
from crypto_backtest_workbench.jobs.task_models import TaskRecord
from crypto_backtest_workbench.storage.repositories.tasks import FileTaskRepository


def test_file_task_repository_persists_and_loads_task(tmp_path) -> None:
    repository = FileTaskRepository(tmp_path)
    task = TaskRecord(
        task_id="single-run:run-001",
        task_kind="single_run",
        status=TaskStatus.FAILED,
        failure_code=FailureCode.CONFIG_INVALID,
        failure_stage="executor",
        failure_message="invalid config",
    )

    path = repository.save_task(task)
    loaded = repository.load_task(task.task_id)

    assert path.exists()
    assert loaded.task_id == task.task_id
    assert loaded.status is TaskStatus.FAILED
    assert loaded.failure_code is FailureCode.CONFIG_INVALID
    assert loaded.failure_stage == "executor"
    assert loaded.failure_message == "invalid config"


def test_file_task_repository_lists_tasks_in_reverse_created_order(tmp_path) -> None:
    repository = FileTaskRepository(tmp_path)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    older = TaskRecord(
        task_id="single-run:run-older",
        task_kind="single_run",
        created_at=start,
        updated_at=start,
    )
    newer = TaskRecord(
        task_id="single-run:run-newer",
        task_kind="single_run",
        created_at=start + timedelta(seconds=1),
        updated_at=start + timedelta(seconds=1),
    )

    repository.save_task(older)
    repository.save_task(newer)

    tasks = repository.list_tasks()

    assert [task.task_id for task in tasks] == [
        "single-run:run-newer",
        "single-run:run-older",
    ]
