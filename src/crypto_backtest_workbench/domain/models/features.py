"""Feature and cache models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models.common import now_utc


@dataclass(slots=True, frozen=True)
class FeatureSpec:
    name: str
    params: dict[str, int | float | bool | str]
    input_price_field: str = "close"
    warmup_bars: int = 0


@dataclass(slots=True, frozen=True)
class FeatureCacheKey:
    dataset_snapshot_id: str
    feature_version: str
    input_price_field: str
    feature_params_hash: str
    warmup_bars: int

    def as_string(self) -> str:
        return (
            f"{self.dataset_snapshot_id}:"
            f"{self.feature_version}:"
            f"{self.input_price_field}:"
            f"{self.feature_params_hash}:"
            f"{self.warmup_bars}"
        )


@dataclass(slots=True)
class FeatureArtifact:
    feature_artifact_id: str
    dataset_snapshot_id: str
    feature_version: str
    feature_params_json: dict[str, object]
    feature_params_hash: str
    input_price_field: str
    warmup_bars: int
    feature_cache_key: str
    storage_uri: str
    depends_on: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=now_utc)

    @classmethod
    def from_cache_key(
        cls,
        *,
        feature_artifact_id: str,
        dataset_snapshot_id: str,
        feature_version: str,
        feature_params_json: dict[str, object],
        feature_params_hash: str,
        input_price_field: str,
        warmup_bars: int,
        storage_uri: str,
        depends_on: tuple[str, ...] = (),
    ) -> "FeatureArtifact":
        key = FeatureCacheKey(
            dataset_snapshot_id=dataset_snapshot_id,
            feature_version=feature_version,
            input_price_field=input_price_field,
            feature_params_hash=feature_params_hash,
            warmup_bars=warmup_bars,
        )
        return cls(
            feature_artifact_id=feature_artifact_id,
            dataset_snapshot_id=dataset_snapshot_id,
            feature_version=feature_version,
            feature_params_json=feature_params_json,
            feature_params_hash=feature_params_hash,
            input_price_field=input_price_field,
            warmup_bars=warmup_bars,
            feature_cache_key=key.as_string(),
            storage_uri=storage_uri,
            depends_on=depends_on,
        )

