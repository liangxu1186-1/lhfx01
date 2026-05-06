"""Read-only run view assembly for CLI and UI consumers."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite, isnan
from pathlib import Path

from crypto_backtest_workbench.domain.models import (
    BacktestRun,
    BenchmarkResult,
    RunManifest,
    StructuredWarning,
)
from crypto_backtest_workbench.engine.analytics.benchmark import BuyAndHoldBenchmarkOutput
from crypto_backtest_workbench.engine.analytics.metrics import RunMetrics
from crypto_backtest_workbench.engine.execution.simulator import ExecutionResult
from crypto_backtest_workbench.storage.repositories import RunRepository


@dataclass(slots=True, frozen=True)
class RunSummaryView:
    run_id: str
    strategy_name: str
    dataset_snapshot_id: str
    symbol: str
    timeframe: str
    fast_period: int | None
    slow_period: int | None
    parameter_summary: str
    leverage: float | None
    status: str
    created_at: datetime
    validation_split_id: str
    total_return: float
    max_drawdown: float
    final_equity: float
    trade_count: int
    win_rate: float
    profit_factor: float | None
    benchmark_return: float | None
    excess_return: float | None
    is_total_return: float | None
    is_excess_return: float | None
    oos_total_return: float | None
    oos_excess_return: float | None
    oos_trade_count: int | None
    oos_win_rate: float | None
    warning_count: int
    order_count: int
    fill_count: int

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True, frozen=True)
class RunDetailView:
    manifest: RunManifest
    run: BacktestRun
    metrics: RunMetrics
    execution: ExecutionResult
    benchmark: BuyAndHoldBenchmarkOutput | None
    validation_summary: dict[str, object] | None


@dataclass(slots=True, frozen=True)
class RunComparisonView:
    run_id: str
    strategy_name: str
    total_return: float
    benchmark_return: float | None
    excess_return: float | None
    final_equity: float
    trade_count: int
    win_rate: float
    profit_factor: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TradeFilter:
    run_ids: tuple[str, ...] = ()
    outcome: str = "all"
    sides: tuple[str, ...] = ()
    min_holding_bars: int | None = None
    max_holding_bars: int | None = None
    reason_query: str | None = None


def list_run_summary_views(run_repository: RunRepository, *, run_ids: list[str] | None = None) -> list[RunSummaryView]:
    summaries: list[RunSummaryView] = []
    for run_id in run_ids or run_repository.list_run_ids():
        manifest = run_repository.load_manifest(run_id)
        run = run_repository.load_run(run_id)
        metrics = run_repository.load_metrics(run_id)
        benchmark = run_repository.load_benchmark_result(run_id)
        validation_summary = run_repository.load_validation_summary(run_id)
        execution_counts = run_repository.count_execution_items(run_id)
        strategy_params = manifest.resolved_config_json.get("strategy_params") or {}
        execution_constraints = manifest.resolved_config_json.get("execution_constraints") or {}
        benchmark_return = benchmark.return_pct if benchmark is not None else None
        excess_return = None
        if benchmark_return is not None:
            excess_return = metrics.total_return - benchmark_return
        is_segment = _load_validation_segment(validation_summary, "is_segment")
        oos_segment = _load_validation_segment(validation_summary, "oos_segment")
        summaries.append(
            RunSummaryView(
                run_id=run.run_id,
                strategy_name=run.strategy_name,
                dataset_snapshot_id=run.dataset_snapshot_id,
                symbol=str(manifest.resolved_config_json.get("symbol") or ""),
                timeframe=str(manifest.resolved_config_json.get("timeframe") or ""),
                fast_period=_coerce_int(strategy_params.get("fast_period")),
                slow_period=_coerce_int(strategy_params.get("slow_period")),
                parameter_summary=_parameter_summary(run.strategy_name, strategy_params, execution_constraints),
                leverage=_coerce_float(execution_constraints.get("leverage")),
                status=run.status.value,
                created_at=run.created_at,
                validation_split_id=run.validation_split_id,
                total_return=metrics.total_return,
                max_drawdown=run_repository.load_max_drawdown(run_id),
                final_equity=metrics.final_equity,
                trade_count=metrics.trade_count,
                win_rate=metrics.win_rate,
                profit_factor=_normalize_float(metrics.profit_factor),
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                is_total_return=_segment_metric_value(is_segment, "total_return"),
                is_excess_return=_segment_numeric_value(is_segment, "excess_return"),
                oos_total_return=_segment_metric_value(oos_segment, "total_return"),
                oos_excess_return=_segment_numeric_value(oos_segment, "excess_return"),
                oos_trade_count=_segment_metric_int_value(oos_segment, "trade_count"),
                oos_win_rate=_segment_metric_value(oos_segment, "win_rate"),
                warning_count=execution_counts["warning_count"],
                order_count=execution_counts["order_count"],
                fill_count=execution_counts["fill_count"],
            )
        )
    return sorted(summaries, key=lambda item: item.created_at, reverse=True)


def load_run_detail_view(run_repository: RunRepository, run_id: str) -> RunDetailView:
    return RunDetailView(
        manifest=run_repository.load_manifest(run_id),
        run=run_repository.load_run(run_id),
        metrics=run_repository.load_metrics(run_id),
        execution=run_repository.load_execution(run_id),
        benchmark=run_repository.load_benchmark(run_id),
        validation_summary=run_repository.load_validation_summary(run_id),
    )


def filter_run_summary_views(
    summaries: list[RunSummaryView],
    *,
    strategy_names: set[str] | None = None,
    statuses: set[str] | None = None,
    symbols: set[str] | None = None,
    validation_split_ids: set[str] | None = None,
    dataset_query: str | None = None,
    min_total_return: float | None = None,
    max_total_return: float | None = None,
    min_trade_count: int | None = None,
    max_trade_count: int | None = None,
    benchmark_mode: str = "all",
) -> list[RunSummaryView]:
    query = (dataset_query or "").strip().lower()
    filtered: list[RunSummaryView] = []
    for summary in summaries:
        if strategy_names and summary.strategy_name not in strategy_names:
            continue
        if statuses and summary.status not in statuses:
            continue
        if symbols and summary.symbol not in symbols:
            continue
        if validation_split_ids and summary.validation_split_id not in validation_split_ids:
            continue
        if min_total_return is not None and summary.total_return < min_total_return:
            continue
        if max_total_return is not None and summary.total_return > max_total_return:
            continue
        if min_trade_count is not None and summary.trade_count < min_trade_count:
            continue
        if max_trade_count is not None and summary.trade_count > max_trade_count:
            continue
        if benchmark_mode == "with" and summary.benchmark_return is None:
            continue
        if benchmark_mode == "without" and summary.benchmark_return is not None:
            continue
        if query and query not in summary.dataset_snapshot_id.lower() and query not in summary.run_id.lower() and query not in summary.symbol.lower():
            continue
        filtered.append(summary)
    return filtered


def build_run_comparison_views(details: list[RunDetailView]) -> list[RunComparisonView]:
    comparison_rows: list[RunComparisonView] = []
    for detail in details:
        benchmark_return = None
        excess_return = None
        if detail.benchmark is not None:
            benchmark_return = detail.benchmark.result.return_pct
            excess_return = detail.metrics.total_return - benchmark_return
        comparison_rows.append(
            RunComparisonView(
                run_id=detail.run.run_id,
                strategy_name=detail.run.strategy_name,
                total_return=detail.metrics.total_return,
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                final_equity=detail.metrics.final_equity,
                trade_count=detail.metrics.trade_count,
                win_rate=detail.metrics.win_rate,
                profit_factor=_normalize_float(detail.metrics.profit_factor),
            )
        )
    return comparison_rows


def build_run_comparison_views_from_summaries(summaries: list[RunSummaryView]) -> list[RunComparisonView]:
    return [
        RunComparisonView(
            run_id=summary.run_id,
            strategy_name=summary.strategy_name,
            total_return=summary.total_return,
            benchmark_return=summary.benchmark_return,
            excess_return=summary.excess_return,
            final_equity=summary.final_equity,
            trade_count=summary.trade_count,
            win_rate=summary.win_rate,
            profit_factor=summary.profit_factor if summary.profit_factor is not None else float("nan"),
        )
        for summary in summaries
    ]


def _parameter_summary(strategy_name: str, strategy_params: dict[str, object], execution_constraints: dict[str, object]) -> str:
    leverage = _coerce_float(execution_constraints.get("leverage"))
    leverage_label = f"l{leverage:g}" if leverage is not None else None
    qty_policy_ref = str(strategy_params.get("qty_policy_ref") or "")
    cash_allocation_pct = _coerce_policy_float(execution_constraints.get("cash_allocation_pct_by_policy"))
    risk_pct_per_trade = _coerce_policy_float(execution_constraints.get("risk_pct_per_trade_by_policy"))
    sizing_label = _sizing_summary(
        qty_policy_ref=qty_policy_ref,
        cash_allocation_pct=cash_allocation_pct,
        risk_pct_per_trade=risk_pct_per_trade,
    )
    if strategy_name == "ema_pullback_atr_v2":
        parts = [
            f"tf{_coerce_int(strategy_params.get('trend_fast_period'))}",
            f"ts{_coerce_int(strategy_params.get('trend_slow_period'))}",
            f"ema{_coerce_int(strategy_params.get('entry_ema_period'))}",
            f"atr{_coerce_int(strategy_params.get('atr_period'))}",
            f"tol{_format_float(_coerce_float(strategy_params.get('atr_entry_tolerance')))}",
            f"sl{_format_float(_coerce_float(strategy_params.get('atr_stop_mult')))}",
            f"rr{_format_float(_coerce_float(strategy_params.get('risk_reward_ratio')))}",
        ]
        if sizing_label is not None:
            parts.append(sizing_label)
        if leverage_label is not None:
            parts.append(leverage_label)
        return " ".join(part for part in parts if part and "None" not in part)

    parts = [
        f"f{_coerce_int(strategy_params.get('fast_period'))}",
        f"s{_coerce_int(strategy_params.get('slow_period'))}",
    ]
    if sizing_label is not None:
        parts.append(sizing_label)
    if leverage_label is not None:
        parts.append(leverage_label)
    return " ".join(part for part in parts if part and "None" not in part)


def build_multi_run_equity_rows(details: list[RunDetailView]) -> list[dict[str, object]]:
    row_by_timestamp: dict[datetime, dict[str, object]] = {}
    for detail in details:
        for row in build_equity_chart_rows(detail):
            timestamp = row["timestamp"]
            merged = row_by_timestamp.setdefault(timestamp, {"timestamp": timestamp})
            merged[f"{detail.run.run_id}_equity"] = row["strategy_equity"]
            if row["benchmark_equity"] is not None:
                merged[f"{detail.run.run_id}_benchmark"] = row["benchmark_equity"]
    return [row_by_timestamp[timestamp] for timestamp in sorted(row_by_timestamp)]


def _sizing_summary(
    *,
    qty_policy_ref: str,
    cash_allocation_pct: float | None,
    risk_pct_per_trade: float | None,
) -> str | None:
    if qty_policy_ref == "percent_of_cash" and cash_allocation_pct is not None:
        return f"cash{_format_float(cash_allocation_pct)}"
    if qty_policy_ref == "risk_pct_of_equity" and risk_pct_per_trade is not None:
        return f"risk{_format_float(risk_pct_per_trade * 100)}%"
    if (
        qty_policy_ref == "risk_pct_of_cash_allocation"
        and cash_allocation_pct is not None
        and risk_pct_per_trade is not None
    ):
        return f"cash{_format_float(cash_allocation_pct)} risk{_format_float(risk_pct_per_trade * 100)}%"
    return None


def _format_float(value: float | None) -> str:
    if value is None:
        return "na"
    return f"{value:g}"


def build_equity_chart_rows(detail: RunDetailView) -> list[dict[str, object]]:
    benchmark_by_timestamp: dict[datetime, BenchmarkResult | object] = {}
    if detail.benchmark is not None:
        benchmark_by_timestamp = {
            point.timestamp: point
            for point in detail.benchmark.equity_points
        }

    rows: list[dict[str, object]] = []
    for point in detail.execution.equity_curve:
        benchmark_point = benchmark_by_timestamp.get(point.timestamp)
        rows.append(
            {
                "timestamp": point.timestamp,
                "strategy_equity": point.equity,
                "benchmark_equity": (
                    None if benchmark_point is None else getattr(benchmark_point, "equity")
                ),
                "strategy_cash": point.cash,
                "strategy_used_margin": point.used_margin,
            }
        )
    return rows


def _coerce_policy_float(value: object) -> float | None:
    if not isinstance(value, dict) or not value:
        return None
    first_value = next(iter(value.values()))
    return _coerce_float(first_value)


def build_trade_rows(detail: RunDetailView, *, data_dir: Path | None = None) -> list[dict[str, object]]:
    feature_rows = _load_feature_rows_by_timestamp(detail=detail, data_dir=data_dir)
    rows: list[dict[str, object]] = []
    for trade in detail.execution.trades:
        entry_signal_meta_json = trade.entry_signal_meta_json
        if feature_rows:
            entry_signal_meta_json = _with_backfilled_entry_features(
                detail=detail,
                trade=trade,
                feature_rows=feature_rows,
            )
        rows.append(
            {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "side": trade.side.value,
                "entry_time": trade.entry_time.isoformat(),
                "entry_price": trade.entry_price,
                "exit_time": trade.exit_time.isoformat() if trade.exit_time is not None else None,
                "exit_price": trade.exit_price,
                "qty": trade.qty,
                "gross_pnl": trade.gross_pnl,
                "fee": trade.fee,
                "net_pnl": trade.net_pnl,
                "return_pct": trade.return_pct,
                "holding_bars": trade.holding_bars,
                "entry_reason": trade.entry_reason,
                "exit_reason": trade.exit_reason,
                "planned_stop_loss_price": trade.planned_stop_loss_price,
                "planned_take_profit_price": trade.planned_take_profit_price,
                "entry_signal_meta_json": entry_signal_meta_json,
                **_entry_feature_columns(entry_signal_meta_json),
            }
        )
    return rows


def _entry_feature_columns(entry_signal_meta_json: object) -> dict[str, object]:
    if not isinstance(entry_signal_meta_json, dict):
        return {}
    feature_values = entry_signal_meta_json.get("feature_values")
    if not isinstance(feature_values, dict):
        return {}
    keys = (
        "pre_entry_momentum_3_pct",
        "pre_entry_momentum_5_pct",
        "pre_entry_consecutive_move",
        "trend_gap_atr",
        "entry_distance_atr",
        "local_range_position_20",
        "local_extreme_distance_atr",
        "breakout_wick_atr",
        "range_chop_score_20",
        "ema_fast_slope_3_atr",
        "atr_pct",
    )
    return {key: value for key in keys if (value := _coerce_float(feature_values.get(key))) is not None}


def _load_feature_rows_by_timestamp(*, detail: RunDetailView, data_dir: Path | None) -> dict[datetime, dict[str, float]]:
    if data_dir is None:
        return {}
    feature_artifact_id = detail.manifest.feature_artifact_id
    if not feature_artifact_id:
        return {}
    path = data_dir / "features" / feature_artifact_id / "feature_rows.csv"
    if not path.exists():
        return {}
    rows: dict[datetime, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp_raw = row.get("timestamp")
            if not timestamp_raw:
                continue
            values: dict[str, float] = {}
            for key, value in row.items():
                if key in {"timestamp", "symbol"} or value in {None, ""}:
                    continue
                try:
                    values[key] = float(value)
                except ValueError:
                    continue
            rows[datetime.fromisoformat(timestamp_raw)] = values
    return rows


def _with_backfilled_entry_features(*, detail: RunDetailView, trade, feature_rows: dict[datetime, dict[str, float]]) -> dict[str, object]:
    meta = dict(trade.entry_signal_meta_json or {})
    raw_features = meta.get("feature_values")
    feature_values = dict(raw_features) if isinstance(raw_features, dict) else {}
    if not feature_values:
        meta["feature_values"] = feature_values
    params = detail.manifest.resolved_config_json.get("strategy_params")
    if not isinstance(params, dict):
        params = {}
    current = feature_rows.get(trade.entry_time)
    if current is None:
        return meta
    timestamps = sorted(feature_rows)
    try:
        index = timestamps.index(trade.entry_time)
    except ValueError:
        return meta
    history = [feature_rows[timestamp] for timestamp in timestamps[: index + 1]]
    side = trade.side.value
    trend_fast_period = _coerce_int(params.get("trend_fast_period"))
    trend_slow_period = _coerce_int(params.get("trend_slow_period"))
    entry_ema_period = _coerce_int(params.get("entry_ema_period")) or 21
    atr_period = _coerce_int(params.get("atr_period")) or 14
    trend_fast_column = f"ema_close_{trend_fast_period}" if trend_fast_period is not None else ""
    trend_slow_column = f"ema_close_{trend_slow_period}" if trend_slow_period is not None else ""
    entry_ema_column = f"ema_close_{entry_ema_period}"
    atr_column = f"atr_{atr_period}"

    def set_missing(key: str, value: float | None) -> None:
        if value is not None and _coerce_float(feature_values.get(key)) is None:
            feature_values[key] = value

    close = _coerce_float(current.get("close"))
    high = _coerce_float(current.get("high"))
    low = _coerce_float(current.get("low"))
    trend_fast = _coerce_float(feature_values.get("trend_fast_ema")) or _coerce_float(current.get(trend_fast_column))
    trend_slow = _coerce_float(feature_values.get("trend_slow_ema")) or _coerce_float(current.get(trend_slow_column))
    entry_ema = _coerce_float(feature_values.get("entry_ema")) or _coerce_float(current.get(entry_ema_column))
    atr = _coerce_float(feature_values.get("atr")) or _coerce_float(current.get(atr_column))
    previous = history[:-1]
    previous_row = previous[-1] if previous else {}
    previous_high = _coerce_float(feature_values.get("previous_high")) or _coerce_float(previous_row.get("high"))
    previous_low = _coerce_float(feature_values.get("previous_low")) or _coerce_float(previous_row.get("low"))

    set_missing("close", close)
    set_missing("high", high)
    set_missing("low", low)
    set_missing("trend_fast_ema", trend_fast)
    set_missing("trend_slow_ema", trend_slow)
    set_missing("entry_ema", entry_ema)
    set_missing("atr", atr)
    set_missing("previous_high", previous_high)
    set_missing("previous_low", previous_low)
    if close is not None and close > 0 and atr is not None:
        set_missing("atr_pct", atr / close)
    if close is not None and close > 0 and trend_fast is not None and trend_slow is not None:
        set_missing("trend_gap_pct", abs(trend_fast - trend_slow) / close)
    if atr is not None and atr > 0 and trend_fast is not None and trend_slow is not None:
        set_missing("trend_gap_atr", abs(trend_fast - trend_slow) / atr)
    if atr is not None and atr > 0 and entry_ema is not None and close is not None:
        touch_value = low if side == "long" else high
        if touch_value is not None:
            set_missing("entry_distance_atr", abs(touch_value - entry_ema) / atr)
        close_distance = close - entry_ema if side == "long" else entry_ema - close
        set_missing("ema_reclaim_strength_atr", close_distance / atr)
        if low is not None and high is not None:
            touched_ema = low <= entry_ema if side == "long" else high >= entry_ema
            closed_back = close >= entry_ema if side == "long" else close <= entry_ema
            set_missing("ema_reclaim", 1.0 if touched_ema and closed_back else 0.0)

    for lookback in (3, 5):
        if len(history) > lookback and close is not None:
            base = _coerce_float(history[-lookback - 1].get("close"))
            if base is not None and base > 0:
                raw = (close - base) / base
                set_missing(f"pre_entry_momentum_{lookback}_pct", raw if side == "long" else -raw)

    consecutive = 0
    for left, right in zip(reversed(history[:-1]), reversed(history)):
        left_close = _coerce_float(left.get("close"))
        right_close = _coerce_float(right.get("close"))
        if left_close is None or right_close is None:
            break
        moved_with_side = right_close > left_close if side == "long" else right_close < left_close
        if not moved_with_side:
            break
        consecutive += 1
    set_missing("pre_entry_consecutive_move", float(consecutive))

    if atr is not None and atr > 0 and len(history) > 3 and trend_fast is not None:
        previous_fast = _coerce_float(history[-4].get(trend_fast_column))
        if previous_fast is not None:
            raw_slope = (trend_fast - previous_fast) / atr
            set_missing("ema_fast_slope_3_atr", raw_slope if side == "long" else -raw_slope)

    prior_20 = previous[-20:]
    if close is not None and prior_20:
        highs = [_coerce_float(row.get("high")) for row in prior_20]
        lows = [_coerce_float(row.get("low")) for row in prior_20]
        closes = [_coerce_float(row.get("close")) for row in prior_20]
        valid_highs = [value for value in highs if value is not None]
        valid_lows = [value for value in lows if value is not None]
        valid_closes = [value for value in closes if value is not None]
        if valid_highs and valid_lows:
            local_high = max(valid_highs)
            local_low = min(valid_lows)
            range_size = local_high - local_low
            if range_size > 0:
                raw_position = (close - local_low) / range_size
                set_missing("local_range_position_20", raw_position if side == "long" else 1 - raw_position)
                if atr is not None and atr > 0:
                    extreme = local_high if side == "long" else local_low
                    set_missing("local_extreme_distance_atr", abs(close - extreme) / atr)
        if len(valid_closes) >= 2:
            net_move = abs(valid_closes[-1] - valid_closes[0])
            gross_move = sum(abs(right - left) for left, right in zip(valid_closes, valid_closes[1:]))
            if gross_move > 0:
                set_missing("range_chop_score_20", max(0.0, min(1.0, 1.0 - net_move / gross_move)))

    if atr is not None and atr > 0 and close is not None:
        if side == "long" and previous_high is not None and high is not None and high > previous_high:
            set_missing("breakout_wick_atr", max(0.0, high - max(close, previous_high)) / atr)
        elif side == "short" and previous_low is not None and low is not None and low < previous_low:
            set_missing("breakout_wick_atr", max(0.0, min(close, previous_low) - low) / atr)
        else:
            set_missing("breakout_wick_atr", 0.0)
    meta["feature_values"] = feature_values
    meta["feature_backfilled"] = True
    return meta


def filter_trade_rows(
    trade_rows: list[dict[str, object]],
    *,
    trade_filter: TradeFilter,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    reason_query = (trade_filter.reason_query or "").strip().lower()

    for trade_row in trade_rows:
        if trade_filter.run_ids and trade_row["run_id"] not in trade_filter.run_ids:
            continue
        if trade_filter.sides and trade_row["side"] not in trade_filter.sides:
            continue
        if trade_filter.min_holding_bars is not None and trade_row["holding_bars"] < trade_filter.min_holding_bars:
            continue
        if trade_filter.max_holding_bars is not None and trade_row["holding_bars"] > trade_filter.max_holding_bars:
            continue
        if not _matches_outcome(outcome=trade_filter.outcome, net_pnl=float(trade_row["net_pnl"])):
            continue
        if reason_query:
            reason_text = " ".join(
                [
                    str(trade_row.get("entry_reason") or ""),
                    str(trade_row.get("exit_reason") or ""),
                ]
            ).lower()
            if reason_query not in reason_text:
                continue
        filtered.append(trade_row)
    return filtered


def build_trade_explorer_rows(details: list[RunDetailView]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for detail in details:
        for trade_row in build_trade_rows(detail):
            enriched = dict(trade_row)
            enriched["run_id"] = detail.run.run_id
            enriched["strategy_name"] = detail.run.strategy_name
            enriched["dataset_snapshot_id"] = detail.run.dataset_snapshot_id
            rows.append(enriched)
    return rows


def build_warning_rows(detail: RunDetailView) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for warning in detail.execution.warnings:
        rows.append(_warning_row(warning))
    return rows


def _warning_row(warning: StructuredWarning) -> dict[str, object]:
    return {
        "warning_id": warning.warning_id,
        "warning_type": warning.warning_type.value,
        "warning_code": warning.warning_code,
        "severity": warning.severity,
        "message": warning.message,
        "created_at": warning.created_at.isoformat(),
    }


def _normalize_float(value: float) -> float | None:
    if not isfinite(value) or isnan(value):
        return None
    return value


def _max_drawdown(equity_curve: list[object]) -> float:
    peak: float | None = None
    max_drawdown = 0.0
    for point in equity_curve:
        equity = float(getattr(point, "equity"))
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _load_validation_segment(
    validation_summary: dict[str, object] | None,
    segment_name: str,
) -> dict[str, object] | None:
    if validation_summary is None:
        return None
    segment = validation_summary.get(segment_name)
    if not isinstance(segment, dict):
        return None
    return segment


def _segment_metric_value(segment: dict[str, object] | None, metric_name: str) -> float | None:
    if not segment:
        return None
    metrics = segment.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(metric_name)
    if value is None:
        return None
    value = float(value)
    if isnan(value):
        return None
    return value


def _segment_metric_int_value(segment: dict[str, object] | None, metric_name: str) -> int | None:
    value = _segment_metric_value(segment, metric_name)
    if value is None:
        return None
    return int(value)


def _segment_numeric_value(segment: dict[str, object] | None, field_name: str) -> float | None:
    if not segment:
        return None
    value = segment.get(field_name)
    if value is None:
        return None
    value = float(value)
    if isnan(value):
        return None
    return value


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _matches_outcome(*, outcome: str, net_pnl: float) -> bool:
    if outcome == "all":
        return True
    if outcome == "winner":
        return net_pnl > 0
    if outcome == "loser":
        return net_pnl < 0
    if outcome == "flat":
        return net_pnl == 0
    raise ValueError(f"Unsupported trade outcome filter: {outcome}")
