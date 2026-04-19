"""Read-only parameter lab assembly for Phase 1 UI consumers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isnan

from crypto_backtest_workbench.app.readmodels.runs import load_run_detail_view
from crypto_backtest_workbench.storage.repositories import RunRepository


@dataclass(slots=True, frozen=True)
class ParameterLabRow:
    run_id: str
    strategy_name: str
    dataset_snapshot_id: str
    symbol: str
    timeframe: str
    validation_split_id: str
    status: str
    created_at: datetime
    fast_period: int | None
    slow_period: int | None
    qty_policy_ref: str | None
    cash_allocation_pct: float | None
    leverage: float | None
    fee_rate: float | None
    slippage_bps: float | None
    total_return: float
    benchmark_return: float | None
    excess_return: float | None
    final_equity: float
    trade_count: int
    win_rate: float
    profit_factor: float | None
    warning_count: int

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class ParameterLabFilter:
    strategy_names: tuple[str, ...] = ()
    validation_split_ids: tuple[str, ...] = ()
    dataset_query: str | None = None
    fast_period_range: tuple[int | None, int | None] = (None, None)
    slow_period_range: tuple[int | None, int | None] = (None, None)
    benchmark_mode: str = "all"


def build_parameter_lab_rows(
    run_repository: RunRepository,
    *,
    run_ids: list[str] | None = None,
) -> list[ParameterLabRow]:
    rows: list[ParameterLabRow] = []
    candidate_run_ids = run_ids or run_repository.list_run_ids()
    for run_id in candidate_run_ids:
        detail = load_run_detail_view(run_repository, run_id)
        strategy_params = detail.manifest.resolved_config_json.get("strategy_params") or {}
        execution_constraints = detail.manifest.resolved_config_json.get("execution_constraints") or {}
        benchmark_return = None
        excess_return = None
        if detail.benchmark is not None:
            benchmark_return = detail.benchmark.result.return_pct
            excess_return = detail.metrics.total_return - benchmark_return
        rows.append(
            ParameterLabRow(
                run_id=detail.run.run_id,
                strategy_name=detail.run.strategy_name,
                dataset_snapshot_id=detail.run.dataset_snapshot_id,
                symbol=str(detail.manifest.resolved_config_json.get("symbol") or ""),
                timeframe=str(detail.manifest.resolved_config_json.get("timeframe") or ""),
                validation_split_id=detail.run.validation_split_id,
                status=detail.run.status.value,
                created_at=detail.run.created_at,
                fast_period=_coerce_int(strategy_params.get("fast_period")),
                slow_period=_coerce_int(strategy_params.get("slow_period")),
                qty_policy_ref=_coerce_str(strategy_params.get("qty_policy_ref")),
                cash_allocation_pct=_coerce_policy_float(execution_constraints.get("cash_allocation_pct_by_policy")),
                leverage=_coerce_float(execution_constraints.get("leverage")),
                fee_rate=_coerce_float(execution_constraints.get("fee_rate")),
                slippage_bps=_coerce_float(execution_constraints.get("slippage_bps")),
                total_return=detail.metrics.total_return,
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                final_equity=detail.metrics.final_equity,
                trade_count=detail.metrics.trade_count,
                win_rate=detail.metrics.win_rate,
                profit_factor=_normalize_float(detail.metrics.profit_factor),
                warning_count=len(detail.execution.warnings),
            )
        )
    return sorted(rows, key=lambda item: item.created_at, reverse=True)


def filter_parameter_lab_rows(
    rows: list[ParameterLabRow],
    *,
    parameter_filter: ParameterLabFilter,
) -> list[ParameterLabRow]:
    query = (parameter_filter.dataset_query or "").strip().lower()
    filtered: list[ParameterLabRow] = []
    for row in rows:
        if parameter_filter.strategy_names and row.strategy_name not in parameter_filter.strategy_names:
            continue
        if parameter_filter.validation_split_ids and row.validation_split_id not in parameter_filter.validation_split_ids:
            continue
        if not _in_optional_int_range(row.fast_period, parameter_filter.fast_period_range):
            continue
        if not _in_optional_int_range(row.slow_period, parameter_filter.slow_period_range):
            continue
        if parameter_filter.benchmark_mode == "with" and row.benchmark_return is None:
            continue
        if parameter_filter.benchmark_mode == "without" and row.benchmark_return is not None:
            continue
        if query:
            haystack = " ".join([row.run_id, row.dataset_snapshot_id, row.symbol]).lower()
            if query not in haystack:
                continue
        filtered.append(row)
    return filtered


def build_parameter_sensitivity_rows(
    rows: list[ParameterLabRow],
    *,
    parameter_name: str,
    metric_name: str,
) -> list[dict[str, object]]:
    grouped: dict[int, list[float]] = {}
    for row in rows:
        parameter_value = getattr(row, parameter_name)
        metric_value = parameter_metric_value(row, metric_name)
        if parameter_value is None or metric_value is None:
            continue
        grouped.setdefault(parameter_value, []).append(metric_value)

    sensitivity_rows: list[dict[str, object]] = []
    for parameter_value in sorted(grouped):
        values = grouped[parameter_value]
        sensitivity_rows.append(
            {
                parameter_name: parameter_value,
                "run_count": len(values),
                "avg_metric": sum(values) / len(values),
                "best_metric": max(values),
            }
        )
    return sensitivity_rows


def parameter_metric_value(row: ParameterLabRow, metric_name: str) -> float | None:
    value = getattr(row, metric_name)
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return None
    return float(value)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_policy_float(value: object) -> float | None:
    if not isinstance(value, dict) or not value:
        return None
    first_value = next(iter(value.values()))
    return _coerce_float(first_value)


def _normalize_float(value: float) -> float | None:
    if isnan(value):
        return None
    return value


def _in_optional_int_range(value: int | None, bounds: tuple[int | None, int | None]) -> bool:
    lower, upper = bounds
    if value is None:
        return lower is None and upper is None
    if lower is not None and value < lower:
        return False
    if upper is not None and value > upper:
        return False
    return True
