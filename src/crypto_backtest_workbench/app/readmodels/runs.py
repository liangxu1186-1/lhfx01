"""Read-only run view assembly for CLI and UI consumers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

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
    status: str
    created_at: datetime
    total_return: float
    final_equity: float
    trade_count: int
    benchmark_return: float | None

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


def list_run_summary_views(run_repository: RunRepository) -> list[RunSummaryView]:
    summaries: list[RunSummaryView] = []
    for run_id in run_repository.list_run_ids():
        run = run_repository.load_run(run_id)
        metrics = run_repository.load_metrics(run_id)
        benchmark = run_repository.load_benchmark(run_id)
        summaries.append(
            RunSummaryView(
                run_id=run.run_id,
                strategy_name=run.strategy_name,
                dataset_snapshot_id=run.dataset_snapshot_id,
                status=run.status.value,
                created_at=run.created_at,
                total_return=metrics.total_return,
                final_equity=metrics.final_equity,
                trade_count=metrics.trade_count,
                benchmark_return=benchmark.result.return_pct if benchmark is not None else None,
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
