"""Task payloads and lifecycle records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models import FailureCode, SearchType, TaskStatus, now_utc


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    task_kind: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    failure_code: FailureCode | None = None
    failure_stage: str | None = None
    failure_message: str | None = None


@dataclass(slots=True)
class SingleRunTaskPayload:
    run_id: str
    dataset_snapshot_id: str
    feature_artifact_id: str
    strategy_name: str
    validation_split_id: str


@dataclass(slots=True)
class ParameterExperimentTaskPayload:
    experiment_id: str
    strategy_name: str
    dataset_bundle_id: str
    search_type: SearchType
    shared_feature_artifact_ids: tuple[str, ...] = ()

