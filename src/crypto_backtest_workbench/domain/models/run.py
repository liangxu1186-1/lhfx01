"""Run-level models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models.common import (
    FailureCode,
    SearchType,
    SeedPolicy,
    TaskStatus,
    now_utc,
)


@dataclass(slots=True)
class MetricPolicy:
    metric_policy_id: str
    return_aggregation_freq: str
    annualization_factor: int
    risk_free_rate: float
    sharpe_formula_version: str


@dataclass(slots=True)
class RunManifest:
    run_id: str
    dataset_snapshot_id: str
    strategy_version: str
    engine_version: str
    execution_policy_id: str
    metric_policy_id: str
    feature_artifact_id: str
    validation_split_id: str
    fee_model_version: str
    slippage_model_version: str
    fee_model_params_json: dict[str, object]
    slippage_model_params_json: dict[str, object]
    benchmark_config_json: dict[str, object]
    resolved_config_json: dict[str, object]
    seed: int | None
    created_at: datetime = field(default_factory=now_utc)

    def validate_required_fields(self) -> None:
        required = {
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "strategy_version": self.strategy_version,
            "engine_version": self.engine_version,
            "execution_policy_id": self.execution_policy_id,
            "metric_policy_id": self.metric_policy_id,
            "feature_artifact_id": self.feature_artifact_id,
            "validation_split_id": self.validation_split_id,
            "fee_model_version": self.fee_model_version,
            "slippage_model_version": self.slippage_model_version,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(f"RunManifest missing required fields: {joined}")


@dataclass(slots=True)
class BacktestRun:
    run_id: str
    strategy_name: str
    strategy_version: str
    dataset_snapshot_id: str
    execution_policy_id: str
    metric_policy_id: str
    feature_artifact_id: str
    engine_version: str
    fee_model_version: str
    slippage_model_version: str
    fee_model_params_json: dict[str, object]
    slippage_model_params_json: dict[str, object]
    validation_split_id: str
    config_hash: str
    resolved_config_uri: str
    benchmark_config_uri: str
    seed: int | None
    run_manifest_uri: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=now_utc)
    failure_code: FailureCode | None = None
    failure_stage: str | None = None
    failure_message: str | None = None
    failure_payload_uri: str | None = None


@dataclass(slots=True)
class ParameterExperiment:
    experiment_id: str
    strategy_name: str
    dataset_bundle_id: str
    validation_split_id: str
    metric_policy_id: str
    benchmark_policy_version: str
    benchmark_config_uri: str
    search_type: SearchType
    search_space_json: dict[str, object]
    base_config_uri: str
    seed_policy: SeedPolicy
    seed: int | None
    shared_feature_artifact_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class ResearchNote:
    note_id: str
    target_type: str
    target_id: str
    content: str
    author: str
    created_at: datetime = field(default_factory=now_utc)

