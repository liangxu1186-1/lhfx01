"""Task record persistence for the local task center."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import FailureCode, TaskStatus
from crypto_backtest_workbench.jobs.task_models import TaskRecord


class TaskRepository(Protocol):
    """Persistence contract for task records."""

    def save_task(self, task: TaskRecord) -> Path:
        """Persist a task record."""

    def load_task(self, task_id: str) -> TaskRecord:
        """Load one persisted task record."""

    def list_task_ids(self) -> list[str]:
        """List persisted task identifiers."""

    def list_tasks(self) -> list[TaskRecord]:
        """List persisted task records."""

    def delete_task(self, task_id: str) -> None:
        """Delete one persisted task record."""


class FileTaskRepository:
    """Filesystem-backed task repository."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_task(self, task: TaskRecord) -> Path:
        tasks_dir = self.base_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        path = self._task_path(task.task_id)
        path.write_text(
            json.dumps(_json_ready(asdict(task)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_task(self, task_id: str) -> TaskRecord:
        payload = json.loads(self._task_path(task_id).read_text(encoding="utf-8"))
        payload["status"] = TaskStatus(payload["status"])
        payload["created_at"] = _parse_iso_datetime(payload["created_at"])
        payload["updated_at"] = _parse_iso_datetime(payload["updated_at"])
        if payload.get("failure_code"):
            payload["failure_code"] = FailureCode(payload["failure_code"])
        return TaskRecord(**payload)

    def list_task_ids(self) -> list[str]:
        tasks_dir = self.base_dir / "tasks"
        if not tasks_dir.exists():
            return []
        task_ids = [
            path.stem
            for path in tasks_dir.iterdir()
            if path.is_file() and path.suffix == ".json"
        ]
        return sorted(task_ids)

    def list_tasks(self) -> list[TaskRecord]:
        tasks = [self.load_task(task_id) for task_id in self.list_task_ids()]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def delete_task(self, task_id: str) -> None:
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        path.unlink()

    def _task_path(self, task_id: str) -> Path:
        return self.base_dir / "tasks" / f"{task_id}.json"


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
