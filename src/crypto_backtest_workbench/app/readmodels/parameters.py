"""Read-only parameter lab assembly for Phase 1 UI consumers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isnan

from crypto_backtest_workbench.app.readmodels.runs import list_run_summary_views
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
    trend_fast_period: int | None
    trend_slow_period: int | None
    entry_ema_period: int | None
    atr_period: int | None
    atr_entry_tolerance: float | None
    atr_stop_mult: float | None
    risk_reward_ratio: float | None
    parameter_summary: str
    signal_filter_summary: str | None
    qty_policy_ref: str | None
    cash_allocation_pct: float | None
    risk_pct_per_trade: float | None
    leverage: float | None
    fee_rate: float | None
    slippage_bps: float | None
    total_return: float
    max_drawdown: float
    benchmark_return: float | None
    excess_return: float | None
    is_total_return: float | None
    is_excess_return: float | None
    oos_total_return: float | None
    oos_excess_return: float | None
    oos_trade_count: int | None
    oos_win_rate: float | None
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
    summary_by_run_id = {
        summary.run_id: summary
        for summary in list_run_summary_views(run_repository, run_ids=candidate_run_ids)
    }
    for run_id in candidate_run_ids:
        summary = summary_by_run_id.get(run_id)
        if summary is None:
            continue
        manifest = run_repository.load_manifest(run_id)
        strategy_params = manifest.resolved_config_json.get("strategy_params") or {}
        execution_constraints = manifest.resolved_config_json.get("execution_constraints") or {}
        rows.append(
            ParameterLabRow(
                run_id=summary.run_id,
                strategy_name=summary.strategy_name,
                dataset_snapshot_id=summary.dataset_snapshot_id,
                symbol=summary.symbol,
                timeframe=summary.timeframe,
                validation_split_id=summary.validation_split_id,
                status=summary.status,
                created_at=summary.created_at,
                fast_period=_coerce_int(strategy_params.get("fast_period")),
                slow_period=_coerce_int(strategy_params.get("slow_period")),
                trend_fast_period=_coerce_int(strategy_params.get("trend_fast_period")),
                trend_slow_period=_coerce_int(strategy_params.get("trend_slow_period")),
                entry_ema_period=_coerce_int(strategy_params.get("entry_ema_period")),
                atr_period=_coerce_int(strategy_params.get("atr_period")),
                atr_entry_tolerance=_coerce_float(strategy_params.get("atr_entry_tolerance")),
                atr_stop_mult=_coerce_float(strategy_params.get("atr_stop_mult")),
                risk_reward_ratio=_coerce_float(strategy_params.get("risk_reward_ratio")),
                parameter_summary=summary.parameter_summary,
                signal_filter_summary=_signal_filter_summary(strategy_params.get("signal_filters")),
                qty_policy_ref=_coerce_str(strategy_params.get("qty_policy_ref")),
                cash_allocation_pct=_coerce_policy_float(execution_constraints.get("cash_allocation_pct_by_policy")),
                risk_pct_per_trade=_coerce_policy_float(execution_constraints.get("risk_pct_per_trade_by_policy")),
                leverage=_coerce_float(execution_constraints.get("leverage")),
                fee_rate=_coerce_float(execution_constraints.get("fee_rate")),
                slippage_bps=_coerce_float(execution_constraints.get("slippage_bps")),
                total_return=summary.total_return,
                max_drawdown=summary.max_drawdown,
                benchmark_return=summary.benchmark_return,
                excess_return=summary.excess_return,
                is_total_return=summary.is_total_return,
                is_excess_return=summary.is_excess_return,
                oos_total_return=summary.oos_total_return,
                oos_excess_return=summary.oos_excess_return,
                oos_trade_count=summary.oos_trade_count,
                oos_win_rate=summary.oos_win_rate,
                final_equity=summary.final_equity,
                trade_count=summary.trade_count,
                win_rate=summary.win_rate,
                profit_factor=_normalize_float(summary.profit_factor),
                warning_count=summary.warning_count,
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


def _signal_filter_summary(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    labels: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        filter_type = str(item.get("filter_type") or "")
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if filter_type == "higher_timeframe_trend":
            labels.append(f"HTF ema{params.get('ema_fast', 50)}/{params.get('ema_slow', 200)}")
        elif filter_type == "atr_percentile":
            labels.append(f"ATR p{params.get('min_percentile', '--')}-{params.get('max_percentile', '--')}")
        elif filter_type == "adx":
            labels.append(f"ADX>={params.get('min_adx', '--')}")
        elif filter_type:
            labels.append(filter_type)
    return " + ".join(labels) if labels else None


def _coerce_policy_float(value: object) -> float | None:
    if not isinstance(value, dict) or not value:
        return None
    first_value = next(iter(value.values()))
    return _coerce_float(first_value)


def _normalize_float(value: float | None) -> float | None:
    if value is None:
        return None
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
