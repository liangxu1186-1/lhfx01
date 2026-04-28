"""Experiment batch persistence for the local workbench."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import ExperimentBatch, SearchType, SeedPolicy


class ExperimentBatchRepository(Protocol):
    """Persistence contract for experiment batches."""

    def save_batch(self, batch: ExperimentBatch) -> Path:
        """Persist batch metadata."""

    def load_batch(self, batch_id: str) -> ExperimentBatch:
        """Load batch metadata."""

    def save_execution_index(self, batch_id: str, payload: dict[str, object]) -> Path:
        """Persist batch execution state and result pointers."""

    def load_execution_index(self, batch_id: str) -> dict[str, object]:
        """Load batch execution state and result pointers."""

    def list_batch_ids(self) -> list[str]:
        """List persisted batch identifiers."""

    def delete_batch(self, batch_id: str) -> None:
        """Delete one persisted experiment batch and its artifacts."""


class FileExperimentBatchRepository:
    """Filesystem-backed experiment batch repository."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_batch(self, batch: ExperimentBatch) -> Path:
        directory = self._batch_dir(batch.batch_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "batch.json"
        path.write_text(
            json.dumps(_json_ready(asdict(batch)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_batch(self, batch_id: str) -> ExperimentBatch:
        payload = json.loads((self._batch_dir(batch_id) / "batch.json").read_text(encoding="utf-8"))
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["search_type"] = SearchType(payload["search_type"])
        payload["seed_policy"] = SeedPolicy(payload["seed_policy"])
        payload["dataset_snapshot_ids"] = tuple(payload.get("dataset_snapshot_ids", ()))
        payload["experiment_ids"] = tuple(payload.get("experiment_ids", ()))
        return ExperimentBatch(**payload)

    def save_execution_index(self, batch_id: str, payload: dict[str, object]) -> Path:
        directory = self._batch_dir(batch_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "execution_index.json"
        path.write_text(
            json.dumps(_json_ready(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_execution_index(self, batch_id: str) -> dict[str, object]:
        path = self._batch_dir(batch_id) / "execution_index.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_batch_ids(self) -> list[str]:
        batches_dir = self.base_dir / "experiment_batches"
        if not batches_dir.exists():
            return []
        batch_ids = [path.name for path in batches_dir.iterdir() if path.is_dir() and (path / "batch.json").exists()]
        return sorted(batch_ids)

    def delete_batch(self, batch_id: str) -> None:
        directory = self._batch_dir(batch_id)
        if not directory.exists():
            raise FileNotFoundError(f"Experiment batch not found: {batch_id}")
        shutil.rmtree(directory)

    def _batch_dir(self, batch_id: str) -> Path:
        return self.base_dir / "experiment_batches" / batch_id


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
