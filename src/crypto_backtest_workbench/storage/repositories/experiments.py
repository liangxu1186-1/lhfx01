"""Parameter experiment persistence for the local workbench."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import ParameterExperiment, SearchType, SeedPolicy


class ParameterExperimentRepository(Protocol):
    """Persistence contract for parameter experiments."""

    def save_experiment(self, experiment: ParameterExperiment) -> Path:
        """Persist experiment metadata."""

    def load_experiment(self, experiment_id: str) -> ParameterExperiment:
        """Load experiment metadata."""

    def save_execution_index(self, experiment_id: str, payload: dict[str, object]) -> Path:
        """Persist experiment execution state and result pointers."""

    def load_execution_index(self, experiment_id: str) -> dict[str, object]:
        """Load experiment execution state and result pointers."""

    def list_experiment_ids(self) -> list[str]:
        """List persisted experiment identifiers."""


class FileParameterExperimentRepository:
    """Filesystem-backed parameter experiment repository."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_experiment(self, experiment: ParameterExperiment) -> Path:
        directory = self._experiment_dir(experiment.experiment_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "experiment.json"
        path.write_text(
            json.dumps(_json_ready(asdict(experiment)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_experiment(self, experiment_id: str) -> ParameterExperiment:
        payload = json.loads((self._experiment_dir(experiment_id) / "experiment.json").read_text(encoding="utf-8"))
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["search_type"] = SearchType(payload["search_type"])
        payload["seed_policy"] = SeedPolicy(payload["seed_policy"])
        payload["shared_feature_artifact_ids"] = tuple(payload.get("shared_feature_artifact_ids", ()))
        return ParameterExperiment(**payload)

    def save_execution_index(self, experiment_id: str, payload: dict[str, object]) -> Path:
        directory = self._experiment_dir(experiment_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "execution_index.json"
        path.write_text(
            json.dumps(_json_ready(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_execution_index(self, experiment_id: str) -> dict[str, object]:
        path = self._experiment_dir(experiment_id) / "execution_index.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_experiment_ids(self) -> list[str]:
        experiments_dir = self.base_dir / "experiments"
        if not experiments_dir.exists():
            return []
        experiment_ids = [
            path.name
            for path in experiments_dir.iterdir()
            if path.is_dir() and (path / "experiment.json").exists()
        ]
        return sorted(experiment_ids)

    def _experiment_dir(self, experiment_id: str) -> Path:
        return self.base_dir / "experiments" / experiment_id


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
