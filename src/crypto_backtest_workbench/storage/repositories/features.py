"""Feature artifact persistence for Phase 1."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import FeatureArtifact
from crypto_backtest_workbench.engine.features.records import FeatureRow


class FeatureRepository(Protocol):
    """Persistence contract for feature artifacts."""

    def build_storage_uri(self, feature_artifact_id: str) -> str:
        """Build the canonical storage URI for a feature artifact data file."""

    def get_artifact(self, feature_cache_key: str) -> FeatureArtifact | None:
        """Lookup a persisted artifact by cache key."""

    def save_artifact(self, artifact: FeatureArtifact) -> Path:
        """Persist feature artifact metadata."""

    def save_feature_rows(
        self,
        *,
        feature_artifact_id: str,
        feature_names: tuple[str, ...],
        rows: list[FeatureRow],
    ) -> Path:
        """Persist materialized feature rows."""

    def load_feature_rows(
        self,
        feature_artifact_id: str,
    ) -> tuple[tuple[str, ...], list[FeatureRow]]:
        """Load persisted feature rows."""


class FileFeatureRepository:
    """Filesystem-backed feature repository for Phase 1."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def build_storage_uri(self, feature_artifact_id: str) -> str:
        return str(self._feature_dir(feature_artifact_id) / "feature_rows.csv")

    def get_artifact(self, feature_cache_key: str) -> FeatureArtifact | None:
        cache_index = self._load_cache_index()
        feature_artifact_id = cache_index.get(feature_cache_key)
        if feature_artifact_id is None:
            return None

        path = self._feature_dir(feature_artifact_id) / "artifact.json"
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["created_at"] = _parse_iso_datetime(payload["created_at"])
        payload["depends_on"] = tuple(payload.get("depends_on", ()))
        return FeatureArtifact(**payload)

    def save_artifact(self, artifact: FeatureArtifact) -> Path:
        directory = self._feature_dir(artifact.feature_artifact_id)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / "artifact.json"
        path.write_text(
            json.dumps(_json_ready(asdict(artifact)), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        cache_index = self._load_cache_index()
        cache_index[artifact.feature_cache_key] = artifact.feature_artifact_id
        self._save_cache_index(cache_index)
        return path

    def save_feature_rows(
        self,
        *,
        feature_artifact_id: str,
        feature_names: tuple[str, ...],
        rows: list[FeatureRow],
    ) -> Path:
        directory = self._feature_dir(feature_artifact_id)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / "feature_rows.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "symbol", *feature_names],
            )
            writer.writeheader()
            for row in rows:
                payload: dict[str, object] = {
                    "timestamp": row.timestamp.isoformat(),
                    "symbol": row.symbol,
                }
                payload.update({name: row.values.get(name) for name in feature_names})
                writer.writerow(payload)
        return path

    def load_feature_rows(
        self,
        feature_artifact_id: str,
    ) -> tuple[tuple[str, ...], list[FeatureRow]]:
        path = self._feature_dir(feature_artifact_id) / "feature_rows.csv"
        if not path.exists():
            raise FileNotFoundError(path)

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("feature_rows.csv is missing a header row")
            feature_names = tuple(reader.fieldnames[2:])
            rows: list[FeatureRow] = []
            for raw_row in reader:
                values = {
                    name: _load_float_or_none(raw_row.get(name))
                    for name in feature_names
                }
                rows.append(
                    FeatureRow(
                        timestamp=_parse_iso_datetime(raw_row["timestamp"]),
                        symbol=raw_row["symbol"],
                        values=values,
                    )
                )
        return feature_names, rows

    def _feature_dir(self, feature_artifact_id: str) -> Path:
        return self.base_dir / "features" / feature_artifact_id

    def _cache_index_path(self) -> Path:
        return self.base_dir / "features" / "cache_index.json"

    def _load_cache_index(self) -> dict[str, str]:
        path = self._cache_index_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_cache_index(self, cache_index: dict[str, str]) -> None:
        path = self._cache_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cache_index, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _load_float_or_none(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _parse_iso_datetime(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)
