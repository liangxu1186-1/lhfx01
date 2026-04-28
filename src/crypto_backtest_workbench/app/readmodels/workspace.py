"""Workspace readmodel assembly for React and API consumers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_backtest_workbench.app.readmodels.parameters import (
    build_parameter_lab_rows,
    build_parameter_sensitivity_rows,
)
from crypto_backtest_workbench.app.readmodels.runs import (
    build_equity_chart_rows,
    build_multi_run_equity_rows,
    build_run_comparison_views,
    build_run_comparison_views_from_summaries,
    build_trade_rows,
    build_warning_rows,
    list_run_summary_views,
    load_run_detail_view,
)
from crypto_backtest_workbench.storage.repositories import FileResearchNoteRepository, FileRunRepository


def build_workspace_snapshot(*, data_dir: Path) -> dict[str, object]:
    run_repository = FileRunRepository(data_dir)
    datasets = _load_dataset_snapshots(data_dir)
    run_ids = run_repository.list_run_ids()
    details = [load_run_detail_view(run_repository, run_id) for run_id in run_ids]
    summaries = list_run_summary_views(run_repository)
    parameter_lab = _build_parameter_lab_payload(run_repository=run_repository, run_ids=run_ids)

    return {
        "generated_at": datetime.now(UTC),
        "source": _build_workspace_source(data_dir=data_dir, run_ids=run_ids, datasets=datasets),
        "datasets": datasets,
        "overview": {
            "summaries": [summary.as_dict() for summary in summaries],
            "comparisons": [view.as_dict() for view in build_run_comparison_views(details)],
            "multi_run_equity": build_multi_run_equity_rows(details),
        },
        "analysis": {
            "runs": [_build_run_workspace(detail) for detail in details],
        },
        "parameter_lab": parameter_lab,
    }


def build_workspace_source(*, data_dir: Path) -> dict[str, object]:
    datasets = _load_dataset_snapshots(data_dir)
    run_ids = FileRunRepository(data_dir).list_run_ids()
    return _build_workspace_source(data_dir=data_dir, run_ids=run_ids, datasets=datasets)


def build_workspace_datasets(*, data_dir: Path) -> list[dict[str, Any]]:
    return _load_dataset_snapshots(data_dir)


def build_workspace_overview(*, data_dir: Path) -> dict[str, object]:
    run_repository = FileRunRepository(data_dir)
    summaries = list_run_summary_views(run_repository)
    return _build_overview_payload(summaries=summaries)


def build_workspace_overview_equity(
    *,
    data_dir: Path,
    run_ids: list[str],
) -> list[dict[str, object]]:
    if not run_ids:
        return []
    run_repository = FileRunRepository(data_dir)
    details = [load_run_detail_view(run_repository, run_id) for run_id in run_ids]
    return build_multi_run_equity_rows(details)


def build_workspace_run_index(*, data_dir: Path) -> list[dict[str, object]]:
    run_repository = FileRunRepository(data_dir)
    return [summary.as_dict() for summary in list_run_summary_views(run_repository)]


def build_workspace_run_detail(*, data_dir: Path, run_id: str) -> dict[str, Any]:
    run_repository = FileRunRepository(data_dir)
    detail = load_run_detail_view(run_repository, run_id)
    research_note_repository = FileResearchNoteRepository(data_dir)
    return _build_run_workspace(detail, research_notes=research_note_repository.list_notes(target_type="run", target_id=run_id))


def build_workspace_parameter_lab(*, data_dir: Path) -> dict[str, object]:
    run_repository = FileRunRepository(data_dir)
    run_ids = run_repository.list_run_ids()
    return _build_parameter_lab_payload(run_repository=run_repository, run_ids=run_ids)


def json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [json_ready(inner) for inner in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def write_workspace_snapshot(*, data_dir: Path, output_path: Path) -> Path:
    payload = build_workspace_snapshot(data_dir=data_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def _build_workspace_source(
    *,
    data_dir: Path,
    run_ids: list[str],
    datasets: list[dict[str, Any]],
) -> dict[str, object]:
    return {
        "data_dir": str(data_dir),
        "run_count": len(run_ids),
        "dataset_count": len(datasets),
    }


def _build_overview_payload(*, summaries: list[Any]) -> dict[str, object]:
    return {
        "summaries": [summary.as_dict() for summary in summaries],
        "comparisons": [view.as_dict() for view in build_run_comparison_views_from_summaries(summaries)],
        "multi_run_equity": [],
    }


def _build_parameter_lab_payload(
    *,
    run_repository: FileRunRepository,
    run_ids: list[str],
) -> dict[str, object]:
    parameter_rows = build_parameter_lab_rows(run_repository, run_ids=run_ids)
    return {
        "rows": [row.as_dict() for row in parameter_rows],
        "fast_period_total_return": _normalize_sensitivity_rows(
            build_parameter_sensitivity_rows(
                parameter_rows,
                parameter_name="fast_period",
                metric_name="total_return",
            ),
            parameter_name="fast_period",
        ),
        "slow_period_total_return": _normalize_sensitivity_rows(
            build_parameter_sensitivity_rows(
                parameter_rows,
                parameter_name="slow_period",
                metric_name="total_return",
            ),
            parameter_name="slow_period",
        ),
    }


def _build_run_workspace(detail: Any, *, research_notes: list[Any] | None = None) -> dict[str, Any]:
    resolved = detail.manifest.resolved_config_json
    return {
        "run_id": detail.run.run_id,
        "strategy_name": detail.run.strategy_name,
        "status": detail.run.status.value,
        "created_at": detail.run.created_at,
        "dataset_snapshot_id": detail.run.dataset_snapshot_id,
        "validation_split_id": detail.run.validation_split_id,
        "symbol": str(resolved.get("symbol") or ""),
        "timeframe": str(resolved.get("timeframe") or ""),
        "manifest": {
            "strategy_version": detail.manifest.strategy_version,
            "engine_version": detail.manifest.engine_version,
            "execution_policy_id": detail.manifest.execution_policy_id,
            "metric_policy_id": detail.manifest.metric_policy_id,
            "feature_artifact_id": detail.manifest.feature_artifact_id,
            "validation_split_id": detail.manifest.validation_split_id,
            "resolved_config_json": detail.manifest.resolved_config_json,
        },
        "metrics": detail.metrics.as_dict(),
        "benchmark": None if detail.benchmark is None else asdict(detail.benchmark.result),
        "validation": detail.validation_summary,
        "research_notes": [] if research_notes is None else research_notes,
        "execution_counts": {
            "order_count": len(detail.execution.orders),
            "fill_count": len(detail.execution.fills),
            "trade_count": len(detail.execution.trades),
            "warning_count": len(detail.execution.warnings),
        },
        "equity_rows": build_equity_chart_rows(detail),
        "trade_rows": build_trade_rows(detail),
        "warning_rows": build_warning_rows(detail),
    }


def _load_dataset_snapshots(data_dir: Path) -> list[dict[str, Any]]:
    datasets_dir = data_dir / "datasets"
    if not datasets_dir.exists():
        return []

    snapshots: list[dict[str, Any]] = []
    for snapshot_path in datasets_dir.glob("*/snapshot.json"):
        snapshots.append(json.loads(snapshot_path.read_text(encoding="utf-8")))
    return sorted(snapshots, key=lambda item: item["created_at"], reverse=True)


def _normalize_sensitivity_rows(
    rows: list[dict[str, Any]],
    *,
    parameter_name: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "parameter_name": parameter_name,
                "parameter_value": row[parameter_name],
                "run_count": row["run_count"],
                "avg_metric": row["avg_metric"],
                "best_metric": row["best_metric"],
            }
        )
    return normalized
