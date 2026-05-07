"""Research-subject and parameter-group readmodels."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from crypto_backtest_workbench.app.readmodels.parameters import ParameterLabRow, build_parameter_lab_rows
from crypto_backtest_workbench.domain.models import ResearchNote
from crypto_backtest_workbench.storage.repositories import (
    FileExperimentBatchRepository,
    FileParameterExperimentRepository,
    ResearchNoteRepository,
    RunRepository,
)

MAX_ROBUST_GAP = 0.2
MAX_ROBUST_AVG_DRAWDOWN = 0.4
MAX_EXCLUDED_WORST_DRAWDOWN = 0.8
MIN_STABLE_TRADE_COUNT = 3
MAX_SCREENING_GAP = 0.2
MAX_SCREENING_DRAWDOWN = 0.5
MIN_SCREENING_PF = 1.05
MIN_AWARE_DATETIME = datetime.min.replace(tzinfo=UTC)


@dataclass(slots=True, frozen=True)
class ResearchSubjectView:
    subject_key: str
    strategy_name: str
    symbol: str
    timeframe: str
    validation_split_id: str
    parameter_group_count: int
    run_count: int
    snapshot_count: int
    latest_run_at: datetime | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.latest_run_at is not None:
            payload["latest_run_at"] = self.latest_run_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class ParameterGroupView:
    group_key: str
    subject_key: str
    strategy_name: str
    symbol: str
    timeframe: str
    validation_split_id: str
    parameter_summary: str
    signal_filter_summary: str | None
    fast_period: int | None
    slow_period: int | None
    trend_fast_period: int | None
    trend_slow_period: int | None
    entry_ema_period: int | None
    atr_period: int | None
    atr_entry_tolerance: float | None
    atr_stop_mult: float | None
    risk_reward_ratio: float | None
    qty_policy_ref: str | None
    cash_allocation_pct: float | None
    risk_pct_per_trade: float | None
    leverage: float | None
    run_count: int
    snapshot_count: int
    avg_total_return: float
    avg_oos_total_return: float | None
    oos_positive_ratio: float | None
    avg_gap: float | None
    avg_max_drawdown: float
    worst_max_drawdown: float
    avg_profit_factor: float | None
    avg_win_rate: float
    min_trade_count: int
    min_oos_trade_count: int | None
    neighbor_count: int
    stable_neighbor_count: int
    neighbor_stability_score: float | None
    risk_matrix_count: int
    research_score: float
    classification: str
    representative_run_id: str | None
    run_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ParameterGroupRunView:
    group_key: str
    run_id: str
    batch_id: str | None
    experiment_id: str | None
    dataset_snapshot_id: str
    created_at: datetime
    total_return: float
    oos_total_return: float | None
    gap: float | None
    max_drawdown: float
    profit_factor: float | None
    trade_count: int
    oos_trade_count: int | None
    win_rate: float
    oos_win_rate: float | None
    final_equity: float

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class ParameterResearchWorkspace:
    subjects: tuple[ResearchSubjectView, ...]
    parameter_groups: tuple[ParameterGroupView, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "subjects": [subject.as_dict() for subject in self.subjects],
            "parameter_groups": [group.as_dict() for group in self.parameter_groups],
        }


@dataclass(slots=True, frozen=True)
class ParameterGroupDetailView:
    group: ParameterGroupView
    runs: tuple[ParameterGroupRunView, ...]
    neighbors: tuple[ParameterGroupView, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "group": self.group.as_dict(),
            "runs": [run.as_dict() for run in self.runs],
            "neighbors": [neighbor.as_dict() for neighbor in self.neighbors],
        }


@dataclass(slots=True, frozen=True)
class ScreeningRunView:
    run_id: str
    strategy_name: str
    dataset_snapshot_id: str
    symbol: str
    timeframe: str
    validation_split_id: str
    parameter_summary: str
    signal_filter_summary: str | None
    fast_period: int | None
    slow_period: int | None
    trend_fast_period: int | None
    trend_slow_period: int | None
    entry_ema_period: int | None
    atr_period: int | None
    atr_entry_tolerance: float | None
    atr_stop_mult: float | None
    risk_reward_ratio: float | None
    qty_policy_ref: str | None
    cash_allocation_pct: float | None
    risk_pct_per_trade: float | None
    leverage: float | None
    score: float
    auto_labels: tuple[str, ...]
    manual_labels: tuple[str, ...]
    pool_status: str
    neighborhood_status: str
    total_return: float
    is_excess_return: float | None
    oos_total_return: float | None
    oos_excess_return: float | None
    is_oos_gap: float | None
    max_drawdown: float
    profit_factor: float | None
    trade_count: int
    oos_trade_count: int | None
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class ResearchCandidateView:
    candidate_id: str
    source_run_ids: tuple[str, ...]
    strategy_name: str
    symbol: str
    timeframe: str
    validation_split_id: str
    entry_structure: dict[str, object]
    risk_profile: dict[str, object]
    representative_run_id: str | None
    representative_run_score: float
    status: str
    latest_note: dict[str, object] | None
    neighborhood_summary: dict[str, object]
    risk_matrix_summary: dict[str, object]
    recommendation: str
    updated_at: datetime | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class StableCandidateView:
    stable_candidate_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    validation_split_id: str
    entry_structure: dict[str, object]
    chosen_risk_profile: dict[str, object]
    evidence_run_ids: tuple[str, ...]
    representative_run_id: str | None
    validation_summary: dict[str, object]
    execution_verification: dict[str, object]
    neighborhood_summary: dict[str, object]
    risk_matrix_summary: dict[str, object]
    final_recommendation: str
    status: str
    latest_note: dict[str, object] | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ResearchWorkflowView:
    screening_pool: dict[str, object]
    research_pool: dict[str, object]
    stable_pool: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "screening_pool": self.screening_pool,
            "research_pool": self.research_pool,
            "stable_pool": self.stable_pool,
        }


def build_parameter_research_workspace(
    run_repository: RunRepository,
    *,
    data_dir: Path | None = None,
) -> ParameterResearchWorkspace:
    rows = build_parameter_lab_rows(run_repository)
    groups = _build_parameter_groups(rows)
    subjects = _build_subjects(rows, groups)
    return ParameterResearchWorkspace(subjects=tuple(subjects), parameter_groups=tuple(groups))


def build_research_workflow(
    run_repository: RunRepository,
    note_repository: ResearchNoteRepository,
    *,
    data_dir: Path | None = None,
) -> ResearchWorkflowView:
    rows = build_parameter_lab_rows(run_repository)
    groups = _build_parameter_groups(rows)
    notes = note_repository.list_notes()
    notes_by_target = _notes_by_target(notes)
    groups_by_key = {group.group_key: group for group in groups}
    execution_verifications_by_candidate = _execution_verifications_by_candidate(run_repository)
    legacy_group_key_map = _legacy_group_key_map(rows)
    group_key_by_run_id: dict[str, str] = {}
    for group in groups:
        for run_id in group.run_ids:
            group_key_by_run_id[run_id] = group.group_key

    screening_runs = [
        _build_screening_run_view(row, notes_by_target=notes_by_target, group_key=group_key_by_run_id.get(row.run_id))
        for row in rows
    ]
    screening_runs.sort(
        key=lambda item: (
            item.pool_status != "excluded",
            item.score,
            item.oos_total_return if item.oos_total_return is not None else -10_000,
            item.profit_factor if item.profit_factor is not None else -10_000,
            -item.max_drawdown,
        ),
        reverse=True,
    )

    research_group_keys = _pool_group_keys(
        notes,
        label="research_pool",
        group_key_by_run_id=group_key_by_run_id,
        known_group_keys=set(groups_by_key),
        legacy_group_key_map=legacy_group_key_map,
    )
    stable_group_keys = _pool_group_keys(
        notes,
        label="stable_pool",
        group_key_by_run_id=group_key_by_run_id,
        known_group_keys=set(groups_by_key),
        legacy_group_key_map=legacy_group_key_map,
    )
    research_group_key_set = set(research_group_keys)
    stable_group_key_set = set(stable_group_keys)
    screening_runs = [
        replace(
            run,
            pool_status=(
                "stable_pool"
                if group_key_by_run_id.get(run.run_id) in stable_group_key_set
                else "research_pool"
                if group_key_by_run_id.get(run.run_id) in research_group_key_set
                else run.pool_status
            ),
        )
        for run in screening_runs
    ]
    research_candidates = [
        _build_research_candidate_view(groups_by_key[group_key], notes_by_target)
        for group_key in research_group_keys
        if group_key in groups_by_key
    ]
    stable_candidates = [
        _build_stable_candidate_view(
            groups_by_key[group_key],
            notes_by_target,
            execution_verification=execution_verifications_by_candidate.get(group_key),
        )
        for group_key in stable_group_keys
        if group_key in groups_by_key
    ]
    research_candidates.sort(key=lambda item: (item.updated_at or MIN_AWARE_DATETIME, item.representative_run_score), reverse=True)
    stable_candidates.sort(key=lambda item: (item.validation_summary.get("score", 0.0), item.stable_candidate_id), reverse=True)
    return ResearchWorkflowView(
        screening_pool={"runs": [run.as_dict() for run in screening_runs]},
        research_pool={"candidates": [candidate.as_dict() for candidate in research_candidates]},
        stable_pool={"candidates": [candidate.as_dict() for candidate in stable_candidates]},
    )


def load_parameter_group_detail(
    run_repository: RunRepository,
    *,
    group_key: str,
    data_dir: Path | None = None,
) -> ParameterGroupDetailView:
    rows = build_parameter_lab_rows(run_repository)
    context = _build_run_context(data_dir) if data_dir is not None else {}
    groups = _build_parameter_groups(rows)
    group_by_key = {group.group_key: group for group in groups}
    group = group_by_key.get(group_key)
    if group is None:
        raise FileNotFoundError(f"Parameter group not found: {group_key}")
    rows_by_run_id = {row.run_id: row for row in rows}
    run_views = [
        _build_run_view(rows_by_run_id[run_id], group_key=group.group_key, context=context)
        for run_id in group.run_ids
        if run_id in rows_by_run_id
    ]
    neighbors = [
        candidate
        for candidate in groups
        if candidate.group_key != group.group_key and _is_neighbor(group, candidate)
    ]
    neighbors.sort(key=lambda item: (item.research_score, item.avg_oos_total_return or -10_000), reverse=True)
    run_views.sort(key=lambda item: item.created_at, reverse=True)
    return ParameterGroupDetailView(group=group, runs=tuple(run_views), neighbors=tuple(neighbors))


def build_subject_key(row: ParameterLabRow) -> str:
    return "|".join([row.strategy_name, row.symbol, row.timeframe, row.validation_split_id])


def build_group_key(row: ParameterLabRow) -> str:
    parts: list[object] = [
        row.strategy_name,
        row.symbol,
        row.timeframe,
        row.validation_split_id,
    ]
    if row.strategy_name == "ema_pullback_atr_v2":
        parts.extend(
            [
                row.trend_fast_period,
                row.trend_slow_period,
                row.entry_ema_period,
                row.atr_period,
                row.atr_entry_tolerance,
                row.atr_stop_mult,
                row.risk_reward_ratio,
                row.signal_filter_summary,
            ]
        )
    else:
        parts.extend([row.fast_period, row.slow_period])
    parts.extend(
        [
            row.qty_policy_ref,
            row.cash_allocation_pct,
            row.risk_pct_per_trade,
            row.leverage,
        ]
    )
    return "|".join(_format_key_part(part) for part in parts)


def build_legacy_group_key(row: ParameterLabRow) -> str:
    parts: list[object] = [
        row.strategy_name,
        row.symbol,
        row.timeframe,
        row.validation_split_id,
    ]
    if row.strategy_name == "ema_pullback_atr_v2":
        parts.extend(
            [
                row.trend_fast_period,
                row.trend_slow_period,
                row.entry_ema_period,
                row.atr_period,
                row.atr_entry_tolerance,
                row.atr_stop_mult,
                row.risk_reward_ratio,
            ]
        )
    else:
        parts.extend([row.fast_period, row.slow_period])
    parts.extend(
        [
            row.qty_policy_ref,
            row.cash_allocation_pct,
            row.risk_pct_per_trade,
            row.leverage,
        ]
    )
    return "|".join(_format_key_part(part) for part in parts)


def _legacy_group_key_map(rows: list[ParameterLabRow]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        if row.signal_filter_summary is None:
            mapping[build_legacy_group_key(row)] = build_group_key(row)
    return mapping


def _build_subjects(rows: list[ParameterLabRow], groups: list[ParameterGroupView]) -> list[ResearchSubjectView]:
    rows_by_subject: dict[str, list[ParameterLabRow]] = {}
    group_count_by_subject: dict[str, int] = {}
    for row in rows:
        rows_by_subject.setdefault(build_subject_key(row), []).append(row)
    for group in groups:
        group_count_by_subject[group.subject_key] = group_count_by_subject.get(group.subject_key, 0) + 1

    subjects: list[ResearchSubjectView] = []
    for subject_key, subject_rows in rows_by_subject.items():
        first = subject_rows[0]
        subjects.append(
            ResearchSubjectView(
                subject_key=subject_key,
                strategy_name=first.strategy_name,
                symbol=first.symbol,
                timeframe=first.timeframe,
                validation_split_id=first.validation_split_id,
                parameter_group_count=group_count_by_subject.get(subject_key, 0),
                run_count=len(subject_rows),
                snapshot_count=len({row.dataset_snapshot_id for row in subject_rows}),
                latest_run_at=max(row.created_at for row in subject_rows),
            )
        )
    return sorted(subjects, key=lambda item: (item.latest_run_at or MIN_AWARE_DATETIME), reverse=True)


def _build_parameter_groups(rows: list[ParameterLabRow]) -> list[ParameterGroupView]:
    grouped_rows: dict[str, list[ParameterLabRow]] = {}
    for row in rows:
        grouped_rows.setdefault(build_group_key(row), []).append(row)

    raw_groups = [_aggregate_group(group_key, group_rows) for group_key, group_rows in grouped_rows.items()]
    group_by_key = {group.group_key: group for group in raw_groups}
    final_groups: list[ParameterGroupView] = []
    for group in raw_groups:
        neighbors = [
            candidate
            for candidate in raw_groups
            if candidate.group_key != group.group_key and _is_neighbor(group, candidate)
        ]
        risk_matrix_groups = [
            candidate
            for candidate in raw_groups
            if _risk_matrix_key(candidate) == _risk_matrix_key(group)
        ]
        stable_neighbor_count = sum(1 for neighbor in neighbors if _is_stable_group(neighbor))
        neighbor_stability_score = stable_neighbor_count / len(neighbors) if neighbors else None
        final_groups.append(
            _replace_group_neighbors(
                group,
                neighbor_count=len(neighbors),
                stable_neighbor_count=stable_neighbor_count,
                neighbor_stability_score=neighbor_stability_score,
                risk_matrix_count=len(risk_matrix_groups),
            )
        )
    final_groups.sort(
        key=lambda item: (
            _classification_priority(item.classification),
            item.research_score,
            item.avg_oos_total_return if item.avg_oos_total_return is not None else -10_000,
        ),
        reverse=True,
    )
    return final_groups


def _aggregate_group(group_key: str, rows: list[ParameterLabRow]) -> ParameterGroupView:
    first = rows[0]
    run_count = len(rows)
    oos_values = [float(row.oos_total_return) for row in rows if row.oos_total_return is not None]
    gap_values = [
        float(row.is_total_return) - float(row.oos_total_return)
        for row in rows
        if row.is_total_return is not None and row.oos_total_return is not None
    ]
    profit_factors = [float(row.profit_factor) for row in rows if row.profit_factor is not None]
    total_returns = [float(row.total_return) for row in rows]
    drawdowns = [float(row.max_drawdown) for row in rows]
    trade_counts = [int(row.trade_count) for row in rows]
    oos_trade_counts = [int(row.oos_trade_count) for row in rows if row.oos_trade_count is not None]
    avg_total_return = sum(total_returns) / run_count
    avg_oos_total_return = sum(oos_values) / len(oos_values) if oos_values else None
    oos_positive_ratio = sum(1 for value in oos_values if value > 0) / len(oos_values) if oos_values else None
    avg_gap = sum(gap_values) / len(gap_values) if gap_values else None
    avg_max_drawdown = sum(drawdowns) / run_count
    worst_max_drawdown = max(drawdowns)
    avg_profit_factor = sum(profit_factors) / len(profit_factors) if profit_factors else None
    avg_win_rate = sum(float(row.win_rate) for row in rows) / run_count
    min_trade_count = min(trade_counts) if trade_counts else 0
    min_oos_trade_count = min(oos_trade_counts) if oos_trade_counts else None
    representative = _representative_run(rows)
    research_score = _score_group(
        avg_total_return=avg_total_return,
        avg_oos_total_return=avg_oos_total_return,
        oos_positive_ratio=oos_positive_ratio,
        avg_gap=avg_gap,
        avg_max_drawdown=avg_max_drawdown,
        worst_max_drawdown=worst_max_drawdown,
        min_trade_count=min_trade_count,
        run_count=run_count,
        snapshot_count=len({row.dataset_snapshot_id for row in rows}),
    )
    classification = _classify_group(
        avg_total_return=avg_total_return,
        avg_oos_total_return=avg_oos_total_return,
        oos_positive_ratio=oos_positive_ratio,
        avg_gap=avg_gap,
        avg_max_drawdown=avg_max_drawdown,
        worst_max_drawdown=worst_max_drawdown,
        min_trade_count=min_trade_count,
        run_count=run_count,
        snapshot_count=len({row.dataset_snapshot_id for row in rows}),
    )
    return ParameterGroupView(
        group_key=group_key,
        subject_key=build_subject_key(first),
        strategy_name=first.strategy_name,
        symbol=first.symbol,
        timeframe=first.timeframe,
        validation_split_id=first.validation_split_id,
        parameter_summary=first.parameter_summary,
        signal_filter_summary=first.signal_filter_summary,
        fast_period=first.fast_period,
        slow_period=first.slow_period,
        trend_fast_period=first.trend_fast_period,
        trend_slow_period=first.trend_slow_period,
        entry_ema_period=first.entry_ema_period,
        atr_period=first.atr_period,
        atr_entry_tolerance=first.atr_entry_tolerance,
        atr_stop_mult=first.atr_stop_mult,
        risk_reward_ratio=first.risk_reward_ratio,
        qty_policy_ref=first.qty_policy_ref,
        cash_allocation_pct=first.cash_allocation_pct,
        risk_pct_per_trade=first.risk_pct_per_trade,
        leverage=first.leverage,
        run_count=run_count,
        snapshot_count=len({row.dataset_snapshot_id for row in rows}),
        avg_total_return=avg_total_return,
        avg_oos_total_return=avg_oos_total_return,
        oos_positive_ratio=oos_positive_ratio,
        avg_gap=avg_gap,
        avg_max_drawdown=avg_max_drawdown,
        worst_max_drawdown=worst_max_drawdown,
        avg_profit_factor=avg_profit_factor,
        avg_win_rate=avg_win_rate,
        min_trade_count=min_trade_count,
        min_oos_trade_count=min_oos_trade_count,
        neighbor_count=0,
        stable_neighbor_count=0,
        neighbor_stability_score=None,
        risk_matrix_count=0,
        research_score=research_score,
        classification=classification,
        representative_run_id=representative.run_id if representative is not None else None,
        run_ids=tuple(row.run_id for row in sorted(rows, key=lambda item: item.created_at, reverse=True)),
    )


def _replace_group_neighbors(
    group: ParameterGroupView,
    *,
    neighbor_count: int,
    stable_neighbor_count: int,
    neighbor_stability_score: float | None,
    risk_matrix_count: int,
) -> ParameterGroupView:
    payload = group.as_dict()
    payload["neighbor_count"] = neighbor_count
    payload["stable_neighbor_count"] = stable_neighbor_count
    payload["neighbor_stability_score"] = neighbor_stability_score
    payload["risk_matrix_count"] = risk_matrix_count
    payload["research_score"] = round(min(100.0, group.research_score + 8.0 * float(neighbor_stability_score or 0.0)), 1)
    payload["classification"] = _classify_with_neighbors(group, neighbor_stability_score, stable_neighbor_count)
    return ParameterGroupView(**payload)


def _classify_with_neighbors(
    group: ParameterGroupView,
    neighbor_stability_score: float | None,
    stable_neighbor_count: int,
) -> str:
    if group.classification == "excluded":
        return "excluded"
    if (
        group.avg_oos_total_return is not None
        and group.avg_oos_total_return > 0
        and (group.oos_positive_ratio or 0.0) >= 0.6
        and (group.avg_gap is None or group.avg_gap <= MAX_ROBUST_GAP)
        and group.avg_max_drawdown <= MAX_ROBUST_AVG_DRAWDOWN
        and stable_neighbor_count >= 1
        and float(neighbor_stability_score or 0.0) >= 0.5
    ):
        return "robust_candidate"
    return group.classification


def _classify_group(
    *,
    avg_total_return: float,
    avg_oos_total_return: float | None,
    oos_positive_ratio: float | None,
    avg_gap: float | None,
    avg_max_drawdown: float,
    worst_max_drawdown: float,
    min_trade_count: int,
    run_count: int,
    snapshot_count: int,
) -> str:
    if (
        avg_total_return <= 0
        or worst_max_drawdown >= MAX_EXCLUDED_WORST_DRAWDOWN
        or (oos_positive_ratio is not None and oos_positive_ratio == 0)
    ):
        return "excluded"
    if avg_oos_total_return is None:
        return "exploratory_candidate"
    if (
        avg_oos_total_return > 0
        and (oos_positive_ratio or 0.0) >= 0.6
        and (avg_gap is None or avg_gap <= MAX_ROBUST_GAP)
        and avg_max_drawdown <= MAX_ROBUST_AVG_DRAWDOWN
        and min_trade_count >= MIN_STABLE_TRADE_COUNT
        and snapshot_count >= 2
    ):
        return "robust_candidate"
    if avg_oos_total_return > 0:
        return "high_return_candidate"
    return "exploratory_candidate"


def _score_group(
    *,
    avg_total_return: float,
    avg_oos_total_return: float | None,
    oos_positive_ratio: float | None,
    avg_gap: float | None,
    avg_max_drawdown: float,
    worst_max_drawdown: float,
    min_trade_count: int,
    run_count: int,
    snapshot_count: int,
) -> float:
    return_score = _score_metric(avg_total_return, 1.0) * 0.25
    oos_score = _score_metric(avg_oos_total_return or 0.0, 0.5) * 0.25
    consistency_score = float(oos_positive_ratio or 0.0) * 0.15
    sample_score = min(1.0, run_count / 6.0) * 0.1 + min(1.0, snapshot_count / 3.0) * 0.1
    trade_score = min(1.0, min_trade_count / 100.0) * 0.05
    drawdown_penalty = min(1.0, avg_max_drawdown / 0.8) * 0.2 + min(1.0, worst_max_drawdown / 0.9) * 0.1
    gap_penalty = min(1.0, max(0.0, avg_gap or 0.0) / 2.0) * 0.1
    score = (return_score + oos_score + consistency_score + sample_score + trade_score) * (1.0 - drawdown_penalty - gap_penalty)
    return round(max(0.0, min(score, 1.0)) * 100.0, 1)


def _score_metric(value: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return max(0.0, min(value / target, 1.0))


def _is_stable_group(group: ParameterGroupView) -> bool:
    return (
        group.classification in {"robust_candidate", "high_return_candidate"}
        and group.avg_oos_total_return is not None
        and group.avg_oos_total_return > 0
        and group.worst_max_drawdown < MAX_EXCLUDED_WORST_DRAWDOWN
    )


def _is_neighbor(source: ParameterGroupView, candidate: ParameterGroupView) -> bool:
    if source.subject_key != candidate.subject_key:
        return False
    if source.strategy_name != candidate.strategy_name:
        return False
    if source.qty_policy_ref != candidate.qty_policy_ref:
        return False
    if source.cash_allocation_pct != candidate.cash_allocation_pct:
        return False
    if source.risk_pct_per_trade != candidate.risk_pct_per_trade:
        return False
    if source.leverage != candidate.leverage:
        return False
    if source.strategy_name == "ema_pullback_atr_v2":
        fixed_fields_match = (
            source.entry_ema_period == candidate.entry_ema_period
            and source.atr_period == candidate.atr_period
            and source.atr_entry_tolerance == candidate.atr_entry_tolerance
            and source.atr_stop_mult == candidate.atr_stop_mult
            and source.risk_reward_ratio == candidate.risk_reward_ratio
        )
        if not fixed_fields_match:
            return False
        return _period_distance(
            source.trend_fast_period,
            source.trend_slow_period,
            candidate.trend_fast_period,
            candidate.trend_slow_period,
        ) == 1
    return _period_distance(source.fast_period, source.slow_period, candidate.fast_period, candidate.slow_period) == 1


def _risk_matrix_key(group: ParameterGroupView) -> tuple[object, ...]:
    key_parts: list[object] = [
        group.strategy_name,
        group.symbol,
        group.timeframe,
    ]
    if group.strategy_name == "ema_pullback_atr_v2":
        key_parts.extend(
            [
                group.trend_fast_period,
                group.trend_slow_period,
                group.entry_ema_period,
                group.atr_period,
                group.atr_entry_tolerance,
                group.atr_stop_mult,
                group.risk_reward_ratio,
            ]
        )
    else:
        key_parts.extend([group.fast_period, group.slow_period])
    return tuple(key_parts)


def _period_distance(
    source_fast: int | None,
    source_slow: int | None,
    candidate_fast: int | None,
    candidate_slow: int | None,
) -> int:
    if None in {source_fast, source_slow, candidate_fast, candidate_slow}:
        return 999
    fast_changed = source_fast != candidate_fast
    slow_changed = source_slow != candidate_slow
    if fast_changed and slow_changed:
        return 2
    if fast_changed or slow_changed:
        return 1
    return 0


def _representative_run(rows: list[ParameterLabRow]) -> ParameterLabRow | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.oos_total_return is not None,
            row.oos_total_return if row.oos_total_return is not None else row.total_return,
            row.total_return,
        ),
    )


def _build_run_view(
    row: ParameterLabRow,
    *,
    group_key: str,
    context: dict[str, tuple[str | None, str | None]],
) -> ParameterGroupRunView:
    experiment_id, batch_id = context.get(row.run_id, (None, None))
    gap = None
    if row.is_total_return is not None and row.oos_total_return is not None:
        gap = row.is_total_return - row.oos_total_return
    return ParameterGroupRunView(
        group_key=group_key,
        run_id=row.run_id,
        batch_id=batch_id,
        experiment_id=experiment_id,
        dataset_snapshot_id=row.dataset_snapshot_id,
        created_at=row.created_at,
        total_return=row.total_return,
        oos_total_return=row.oos_total_return,
        gap=gap,
        max_drawdown=row.max_drawdown,
        profit_factor=row.profit_factor,
        trade_count=row.trade_count,
        oos_trade_count=row.oos_trade_count,
        win_rate=row.win_rate,
        oos_win_rate=row.oos_win_rate,
        final_equity=row.final_equity,
    )


def _build_run_context(data_dir: Path) -> dict[str, tuple[str | None, str | None]]:
    context: dict[str, tuple[str | None, str | None]] = {}
    experiment_repository = FileParameterExperimentRepository(data_dir)
    batch_repository = FileExperimentBatchRepository(data_dir)
    experiment_to_batch: dict[str, str] = {}
    for batch_id in batch_repository.list_batch_ids():
        try:
            batch = batch_repository.load_batch(batch_id)
        except FileNotFoundError:
            continue
        for experiment_id in batch.experiment_ids:
            experiment_to_batch[str(experiment_id)] = batch_id
    for experiment_id in experiment_repository.list_experiment_ids():
        try:
            execution = experiment_repository.load_execution_index(experiment_id)
        except FileNotFoundError:
            continue
        batch_id = experiment_to_batch.get(experiment_id)
        for run_id in execution.get("run_ids", []):
            context[str(run_id)] = (experiment_id, batch_id)
    return context


def _format_key_part(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _classification_priority(classification: str) -> int:
    return {
        "robust_candidate": 4,
        "high_return_candidate": 3,
        "exploratory_candidate": 2,
        "excluded": 1,
    }.get(classification, 0)


def build_research_candidate_id(row: ParameterLabRow) -> str:
    return "|".join(_format_key_part(part) for part in _candidate_key_parts(row, include_risk=True))


def build_research_entry_id(row: ParameterLabRow) -> str:
    return "|".join(_format_key_part(part) for part in _candidate_key_parts(row, include_risk=False))


def _candidate_key_parts(row: ParameterLabRow, *, include_risk: bool) -> list[object]:
    parts: list[object] = [
        row.strategy_name,
        row.symbol,
        row.timeframe,
        row.validation_split_id,
    ]
    if row.strategy_name == "ema_pullback_atr_v2":
        parts.extend(
            [
                row.trend_fast_period,
                row.trend_slow_period,
                row.entry_ema_period,
                row.atr_period,
                row.atr_entry_tolerance,
                row.atr_stop_mult,
                row.risk_reward_ratio,
            ]
        )
    else:
        parts.extend([row.fast_period, row.slow_period])
    if include_risk:
        parts.extend([row.qty_policy_ref, row.cash_allocation_pct, row.risk_pct_per_trade, row.leverage])
    return parts


def _notes_by_target(notes: list[ResearchNote]) -> dict[tuple[str, str], list[ResearchNote]]:
    grouped: dict[tuple[str, str], list[ResearchNote]] = {}
    for note in notes:
        grouped.setdefault((note.target_type, note.target_id), []).append(note)
    for target_notes in grouped.values():
        target_notes.sort(key=lambda note: note.created_at, reverse=True)
    return grouped


def _build_screening_run_view(
    row: ParameterLabRow,
    *,
    notes_by_target: dict[tuple[str, str], list[ResearchNote]],
    group_key: str | None,
) -> ScreeningRunView:
    score = _score_screening_run(row)
    auto_labels = tuple(_auto_screening_labels(row, score=score, group_key=group_key))
    run_notes = notes_by_target.get(("run", row.run_id), [])
    manual_labels = tuple(sorted({label for note in run_notes for label in note.labels}))
    pool_status = "excluded" if "screening_pool_excluded" in manual_labels else "active"
    if "research_pool" in manual_labels:
        pool_status = "research_pool"
    if "stable_pool" in manual_labels:
        pool_status = "stable_pool"
    gap = _run_gap(row)
    return ScreeningRunView(
        run_id=row.run_id,
        strategy_name=row.strategy_name,
        dataset_snapshot_id=row.dataset_snapshot_id,
        symbol=row.symbol,
        timeframe=row.timeframe,
        validation_split_id=row.validation_split_id,
        parameter_summary=row.parameter_summary,
        signal_filter_summary=row.signal_filter_summary,
        fast_period=row.fast_period,
        slow_period=row.slow_period,
        trend_fast_period=row.trend_fast_period,
        trend_slow_period=row.trend_slow_period,
        entry_ema_period=row.entry_ema_period,
        atr_period=row.atr_period,
        atr_entry_tolerance=row.atr_entry_tolerance,
        atr_stop_mult=row.atr_stop_mult,
        risk_reward_ratio=row.risk_reward_ratio,
        qty_policy_ref=row.qty_policy_ref,
        cash_allocation_pct=row.cash_allocation_pct,
        risk_pct_per_trade=row.risk_pct_per_trade,
        leverage=row.leverage,
        score=score,
        auto_labels=auto_labels,
        manual_labels=manual_labels,
        pool_status=pool_status,
        neighborhood_status="已跑" if group_key else "邻域待跑",
        total_return=row.total_return,
        is_excess_return=row.is_excess_return,
        oos_total_return=row.oos_total_return,
        oos_excess_return=row.oos_excess_return,
        is_oos_gap=gap,
        max_drawdown=row.max_drawdown,
        profit_factor=row.profit_factor,
        trade_count=row.trade_count,
        oos_trade_count=row.oos_trade_count,
        created_at=row.created_at,
    )


def _score_screening_run(row: ParameterLabRow) -> float:
    oos_return = row.oos_total_return if row.oos_total_return is not None else row.total_return
    oos_excess = row.oos_excess_return if row.oos_excess_return is not None else row.excess_return or 0.0
    pf = row.profit_factor or 0.0
    sample = min(1.0, row.trade_count / 100.0)
    oos_sample = min(1.0, (row.oos_trade_count or 0) / 30.0)
    gap = max(0.0, _run_gap(row) or 0.0)
    risk_penalty = 0.0
    if row.leverage is not None and row.leverage > 5:
        risk_penalty += min(0.3, (row.leverage - 5) / 20)
    if row.risk_pct_per_trade is not None and row.risk_pct_per_trade > 0.05:
        risk_penalty += min(0.3, (row.risk_pct_per_trade - 0.05) / 0.2)
    raw = (
        0.28 * _score_metric(oos_return, 0.5)
        + 0.18 * _score_metric(oos_excess, 0.3)
        + 0.18 * _score_metric(pf - 1.0, 1.0)
        + 0.16 * (0.55 * sample + 0.45 * oos_sample)
    )
    penalty = min(0.75, 0.26 * min(1.0, row.max_drawdown / 0.8) + 0.14 * min(1.0, gap / 0.5) + risk_penalty)
    return round(max(0.0, min(1.0, raw * (1.0 - penalty))) * 100.0, 1)


def _auto_screening_labels(row: ParameterLabRow, *, score: float, group_key: str | None) -> list[str]:
    labels: list[str] = []
    gap = _run_gap(row)
    if score >= 45 and (row.oos_total_return is None or row.oos_total_return > 0):
        labels.append("值得研究")
    if row.total_return >= 0.5:
        labels.append("高收益")
    if row.oos_total_return is not None and row.oos_total_return > 0:
        labels.append("OOS 强")
    if gap is not None and gap <= MAX_SCREENING_GAP:
        labels.append("Gap 小")
    if gap is not None and gap > MAX_SCREENING_GAP:
        labels.append("Gap 大")
    if row.max_drawdown > MAX_SCREENING_DRAWDOWN:
        labels.append("回撤过大")
    if row.profit_factor is not None and row.profit_factor < MIN_SCREENING_PF:
        labels.append("PF 偏低")
    if row.trade_count < MIN_STABLE_TRADE_COUNT or (row.oos_trade_count is not None and row.oos_trade_count < 1):
        labels.append("样本不足")
    if (row.leverage is not None and row.leverage > 5) or (row.risk_pct_per_trade is not None and row.risk_pct_per_trade > 0.05):
        labels.append("风险偏激")
    if group_key is None:
        labels.append("邻域待跑")
    if row.total_return <= 0 or (row.oos_total_return is not None and row.oos_total_return <= 0) or row.max_drawdown >= MAX_EXCLUDED_WORST_DRAWDOWN:
        labels.append("建议排除")
    return labels


def _pool_group_keys(
    notes: list[ResearchNote],
    *,
    label: str,
    group_key_by_run_id: dict[str, str],
    known_group_keys: set[str],
    legacy_group_key_map: dict[str, str],
) -> list[str]:
    group_keys: set[str] = set()
    inactive_group_keys: set[str] = set()
    for note in notes:
        note_labels = set(note.labels)
        target_group_key = _note_group_key(
            note,
            group_key_by_run_id=group_key_by_run_id,
            known_group_keys=known_group_keys,
            legacy_group_key_map=legacy_group_key_map,
        )
        if target_group_key is None:
            continue
        if note.decision_status in {"rejected", "archived"}:
            inactive_group_keys.add(target_group_key)
            continue
        if label in note_labels or (label == "research_pool" and "tracking" in note_labels):
            group_keys.add(target_group_key)
    return sorted(group_keys - inactive_group_keys)


def _note_group_key(
    note: ResearchNote,
    *,
    group_key_by_run_id: dict[str, str],
    known_group_keys: set[str],
    legacy_group_key_map: dict[str, str],
) -> str | None:
    if note.linked_parameter_group and note.linked_parameter_group in known_group_keys:
        return note.linked_parameter_group
    if note.linked_parameter_group and note.linked_parameter_group in legacy_group_key_map:
        return legacy_group_key_map[note.linked_parameter_group]
    if note.target_type in {"research_candidate", "stable_candidate", "parameter_group"} and note.target_id in known_group_keys:
        return note.target_id
    if note.target_type in {"research_candidate", "stable_candidate", "parameter_group"} and note.target_id in legacy_group_key_map:
        return legacy_group_key_map[note.target_id]
    if note.target_type == "run":
        return group_key_by_run_id.get(note.target_id)
    return None


def _build_research_candidate_view(
    group: ParameterGroupView,
    notes_by_target: dict[tuple[str, str], list[ResearchNote]],
) -> ResearchCandidateView:
    candidate_notes = _candidate_notes(group, notes_by_target)
    latest_note = candidate_notes[0] if candidate_notes else None
    return ResearchCandidateView(
        candidate_id=group.group_key,
        source_run_ids=group.run_ids,
        strategy_name=group.strategy_name,
        symbol=group.symbol,
        timeframe=group.timeframe,
        validation_split_id=group.validation_split_id,
        entry_structure=_entry_structure(group),
        risk_profile=_risk_profile(group),
        representative_run_id=group.representative_run_id,
        representative_run_score=group.research_score,
        status=_research_status(latest_note, group),
        latest_note=json_ready_note(latest_note),
        neighborhood_summary=_neighborhood_summary(group),
        risk_matrix_summary=_risk_matrix_summary(group),
        recommendation=_candidate_recommendation(group),
        updated_at=latest_note.created_at if latest_note else None,
    )


def _build_stable_candidate_view(
    group: ParameterGroupView,
    notes_by_target: dict[tuple[str, str], list[ResearchNote]],
    *,
    execution_verification: dict[str, object] | None = None,
) -> StableCandidateView:
    candidate_notes = _candidate_notes(group, notes_by_target)
    latest_note = candidate_notes[0] if candidate_notes else None
    verification = execution_verification or _empty_execution_verification()
    return StableCandidateView(
        stable_candidate_id=group.group_key,
        strategy_name=group.strategy_name,
        symbol=group.symbol,
        timeframe=group.timeframe,
        validation_split_id=group.validation_split_id,
        entry_structure=_entry_structure(group),
        chosen_risk_profile=_risk_profile(group),
        evidence_run_ids=group.run_ids,
        representative_run_id=group.representative_run_id,
        validation_summary=_validation_summary(group),
        execution_verification=verification,
        neighborhood_summary=_neighborhood_summary(group),
        risk_matrix_summary=_risk_matrix_summary(group),
        final_recommendation=latest_note.decision_reason if latest_note and latest_note.decision_reason else _candidate_recommendation(group),
        status=_stable_candidate_status(latest_note, verification),
        latest_note=json_ready_note(latest_note),
    )


def _candidate_notes(
    group: ParameterGroupView,
    notes_by_target: dict[tuple[str, str], list[ResearchNote]],
) -> list[ResearchNote]:
    notes: list[ResearchNote] = []
    notes.extend(notes_by_target.get(("research_candidate", group.group_key), []))
    notes.extend(notes_by_target.get(("stable_candidate", group.group_key), []))
    notes.extend(notes_by_target.get(("parameter_group", group.group_key), []))
    for run_id in group.run_ids:
        for note in notes_by_target.get(("run", run_id), []):
            if note.linked_parameter_group is None or note.linked_parameter_group == group.group_key:
                notes.append(note)
    return sorted({note.note_id: note for note in notes}.values(), key=lambda note: note.created_at, reverse=True)


def _execution_verifications_by_candidate(run_repository: RunRepository) -> dict[str, dict[str, object]]:
    verifications: dict[str, dict[str, object]] = {}
    for run_id in run_repository.list_run_ids():
        try:
            manifest = run_repository.load_manifest(run_id)
        except FileNotFoundError:
            continue
        resolved = manifest.resolved_config_json
        if resolved.get("run_type") != "execution_verification":
            continue
        candidate_id = str(resolved.get("stable_candidate_id") or "")
        if not candidate_id:
            continue
        try:
            run = run_repository.load_run(run_id)
            metrics = run_repository.load_metrics(run_id)
            max_drawdown = run_repository.load_max_drawdown(run_id)
            validation_summary = run_repository.load_validation_summary(run_id)
        except FileNotFoundError:
            continue
        summary = {
            "total_return": metrics.total_return,
            "max_drawdown": max_drawdown,
            "profit_factor": metrics.profit_factor,
            "win_rate": metrics.win_rate,
            "trade_count": metrics.trade_count,
            "final_equity": metrics.final_equity,
        }
        payload = {
            "latest_run_id": run_id,
            "parent_run_id": str(resolved.get("parent_run_id") or ""),
            "status": _execution_verification_status(summary),
            "strategy_timeframe": str(resolved.get("strategy_timeframe") or ""),
            "execution_timeframe": str(resolved.get("execution_timeframe") or ""),
            "execution_model_version": str(resolved.get("execution_model_version") or ""),
            "summary": summary,
            "validation": _execution_validation_payload(validation_summary),
            "created_at": run.created_at.isoformat(),
        }
        current = verifications.get(candidate_id)
        if current is None or str(payload["created_at"]) > str(current.get("created_at") or ""):
            verifications[candidate_id] = payload
    return verifications


def _empty_execution_verification() -> dict[str, object]:
    return {
        "latest_run_id": None,
        "parent_run_id": None,
        "status": "not_run",
        "strategy_timeframe": None,
        "execution_timeframe": None,
        "execution_model_version": None,
        "summary": {},
        "validation": None,
    }


def _execution_validation_payload(validation_summary: dict[str, object] | None) -> dict[str, object] | None:
    if validation_summary is None:
        return None
    is_segment = validation_summary.get("is_segment")
    oos_segment = validation_summary.get("oos_segment")
    if not isinstance(is_segment, dict) or not isinstance(oos_segment, dict):
        return None
    is_metrics = is_segment.get("metrics")
    oos_metrics = oos_segment.get("metrics")
    if not isinstance(is_metrics, dict) or not isinstance(oos_metrics, dict):
        return None
    return {
        "validation_split_id": validation_summary.get("validation_split_id"),
        "is_total_return": is_metrics.get("total_return"),
        "is_max_drawdown": is_metrics.get("max_drawdown"),
        "is_profit_factor": is_metrics.get("profit_factor"),
        "is_win_rate": is_metrics.get("win_rate"),
        "is_trade_count": is_metrics.get("trade_count"),
        "is_final_equity": is_metrics.get("final_equity"),
        "is_analysis_bar_count": is_segment.get("analysis_bar_count"),
        "oos_total_return": oos_metrics.get("total_return"),
        "oos_max_drawdown": oos_metrics.get("max_drawdown"),
        "oos_profit_factor": oos_metrics.get("profit_factor"),
        "oos_win_rate": oos_metrics.get("win_rate"),
        "oos_trade_count": oos_metrics.get("trade_count"),
        "oos_final_equity": oos_metrics.get("final_equity"),
        "oos_analysis_bar_count": oos_segment.get("analysis_bar_count"),
    }


def _execution_verification_status(summary: dict[str, object]) -> str:
    total_return = _optional_numeric(summary.get("total_return"))
    max_drawdown = _optional_numeric(summary.get("max_drawdown"))
    profit_factor = _optional_numeric(summary.get("profit_factor"))
    trade_count = int(summary.get("trade_count") or 0)
    if trade_count <= 0:
        return "failed"
    if total_return is not None and total_return <= 0:
        return "failed"
    if max_drawdown is not None and max_drawdown >= MAX_ROBUST_AVG_DRAWDOWN:
        return "failed"
    if profit_factor is not None and profit_factor < MIN_SCREENING_PF:
        return "failed"
    return "passed"


def _stable_candidate_status(note: ResearchNote | None, verification: dict[str, object]) -> str:
    if verification.get("status") == "passed":
        return "execution_verified"
    if note is not None and note.decision_status not in {"approved", "candidate"}:
        return note.decision_status
    return "research_stable"


def _optional_numeric(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _research_status(note: ResearchNote | None, group: ParameterGroupView) -> str:
    if note is not None:
        return {
            "candidate": "待研究",
            "observing": "继续观察",
            "approved": "可入稳定池",
            "rejected": "拒绝",
            "archived": "归档",
        }.get(note.decision_status, note.decision_status)
    if group.neighbor_count == 0:
        return "邻域待跑"
    if group.classification == "robust_candidate":
        return "可入稳定池"
    return "待研究"


def _entry_structure(group: ParameterGroupView) -> dict[str, object]:
    if group.strategy_name == "ema_pullback_atr_v2":
        return {
            "trend_fast_period": group.trend_fast_period,
            "trend_slow_period": group.trend_slow_period,
            "entry_ema_period": group.entry_ema_period,
            "atr_period": group.atr_period,
            "atr_entry_tolerance": group.atr_entry_tolerance,
            "atr_stop_mult": group.atr_stop_mult,
            "risk_reward_ratio": group.risk_reward_ratio,
        }
    return {"fast_period": group.fast_period, "slow_period": group.slow_period}


def _risk_profile(group: ParameterGroupView) -> dict[str, object]:
    return {
        "qty_policy_ref": group.qty_policy_ref,
        "cash_allocation_pct": group.cash_allocation_pct,
        "risk_pct_per_trade": group.risk_pct_per_trade,
        "leverage": group.leverage,
    }


def _neighborhood_summary(group: ParameterGroupView) -> dict[str, object]:
    if group.neighbor_count == 0:
        verdict = "样本不足"
    elif (group.neighbor_stability_score or 0.0) >= 0.5:
        verdict = "稳定"
    elif group.stable_neighbor_count > 0:
        verdict = "观察"
    else:
        verdict = "不稳定"
    return {
        "status": "已跑" if group.neighbor_count else "未跑",
        "neighbor_count": group.neighbor_count,
        "stable_neighbor_count": group.stable_neighbor_count,
        "stable_score": group.neighbor_stability_score,
        "verdict": verdict,
    }


def _risk_matrix_summary(group: ParameterGroupView) -> dict[str, object]:
    status = "已跑" if group.risk_matrix_count > 1 else "未跑"
    return {
        "status": status,
        "group_count": group.risk_matrix_count,
        "run_count": group.run_count,
        "avg_oos_total_return": group.avg_oos_total_return,
        "worst_max_drawdown": group.worst_max_drawdown,
        "avg_profit_factor": group.avg_profit_factor,
        "verdict": "观察" if status == "未跑" else _candidate_recommendation(group),
    }


def _validation_summary(group: ParameterGroupView) -> dict[str, object]:
    return {
        "score": group.research_score,
        "avg_total_return": group.avg_total_return,
        "avg_oos_total_return": group.avg_oos_total_return,
        "avg_gap": group.avg_gap,
        "avg_max_drawdown": group.avg_max_drawdown,
        "worst_max_drawdown": group.worst_max_drawdown,
        "avg_profit_factor": group.avg_profit_factor,
        "min_trade_count": group.min_trade_count,
        "min_oos_trade_count": group.min_oos_trade_count,
    }


def _candidate_recommendation(group: ParameterGroupView) -> str:
    if group.classification == "robust_candidate":
        return "建议进入稳定池"
    if group.classification == "high_return_candidate":
        return "建议降风险后再评估"
    if group.classification == "excluded":
        return "建议归档"
    return "继续观察"


def _run_gap(row: ParameterLabRow) -> float | None:
    if row.is_total_return is None or row.oos_total_return is None:
        return None
    return row.is_total_return - row.oos_total_return


def json_ready_note(note: ResearchNote | None) -> dict[str, object] | None:
    if note is None:
        return None
    payload = asdict(note)
    payload["created_at"] = note.created_at.isoformat()
    return payload
