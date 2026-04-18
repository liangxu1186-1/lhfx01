"""Read-only run view assembly for CLI and UI consumers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isnan

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
    status: str
    created_at: datetime
    validation_split_id: str
    total_return: float
    final_equity: float
    trade_count: int
    win_rate: float
    profit_factor: float | None
    benchmark_return: float | None
    excess_return: float | None
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


def list_run_summary_views(run_repository: RunRepository) -> list[RunSummaryView]:
    summaries: list[RunSummaryView] = []
    for run_id in run_repository.list_run_ids():
        manifest = run_repository.load_manifest(run_id)
        run = run_repository.load_run(run_id)
        metrics = run_repository.load_metrics(run_id)
        benchmark = run_repository.load_benchmark(run_id)
        execution = run_repository.load_execution(run_id)
        benchmark_return = benchmark.result.return_pct if benchmark is not None else None
        excess_return = None
        if benchmark_return is not None:
            excess_return = metrics.total_return - benchmark_return
        summaries.append(
            RunSummaryView(
                run_id=run.run_id,
                strategy_name=run.strategy_name,
                dataset_snapshot_id=run.dataset_snapshot_id,
                symbol=str(manifest.resolved_config_json.get("symbol") or ""),
                timeframe=str(manifest.resolved_config_json.get("timeframe") or ""),
                status=run.status.value,
                created_at=run.created_at,
                validation_split_id=run.validation_split_id,
                total_return=metrics.total_return,
                final_equity=metrics.final_equity,
                trade_count=metrics.trade_count,
                win_rate=metrics.win_rate,
                profit_factor=_normalize_float(metrics.profit_factor),
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                warning_count=len(execution.warnings),
                order_count=len(execution.orders),
                fill_count=len(execution.fills),
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


def build_trade_rows(detail: RunDetailView) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade in detail.execution.trades:
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
            }
        )
    return rows


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
    if isnan(value):
        return None
    return value


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
