"""Run result persistence for Phase 1."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar

from crypto_backtest_workbench.domain.models import (
    BacktestRun,
    BenchmarkResult,
    FillEvent,
    OrderRequest,
    RejectReasonCode,
    RunManifest,
    Side,
    StructuredWarning,
    TaskStatus,
    TradeRecord,
    WarningType,
)
from crypto_backtest_workbench.domain.models.common import FailureCode
from crypto_backtest_workbench.engine.analytics.benchmark import (
    BenchmarkDailyReturn,
    BenchmarkEquityPoint,
    BuyAndHoldBenchmarkOutput,
)
from crypto_backtest_workbench.engine.analytics.metrics import EquityPoint, RunMetrics
from crypto_backtest_workbench.engine.execution.simulator import ExecutionResult
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot

if TYPE_CHECKING:
    from crypto_backtest_workbench.jobs.single_run import SingleRunResult


class RunRepository(Protocol):
    """Persistence contract for single-run outputs."""

    def save_single_run_result(self, result: SingleRunResult) -> dict[str, object]:
        """Persist manifest, summary, execution outputs, metrics and benchmark artifacts."""

    def list_run_ids(self) -> list[str]:
        """List persisted run identifiers."""

    def load_manifest(self, run_id: str) -> RunManifest:
        """Load a persisted run manifest."""

    def load_run(self, run_id: str) -> BacktestRun:
        """Load a persisted run summary."""

    def load_execution(self, run_id: str) -> ExecutionResult:
        """Load persisted execution outputs."""

    def load_metrics(self, run_id: str) -> RunMetrics:
        """Load persisted run metrics."""

    def load_benchmark(self, run_id: str) -> BuyAndHoldBenchmarkOutput | None:
        """Load persisted benchmark output if present."""


class FileRunRepository:
    """Filesystem-backed repository for run results."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_single_run_result(self, result: SingleRunResult) -> dict[str, object]:
        run_id = result.run.run_id
        benchmark_paths = None
        if result.benchmark_output is not None:
            benchmark_paths = self.save_benchmark(run_id=run_id, output=result.benchmark_output)

        return {
            "manifest": self.save_manifest(result.manifest),
            "run": self.save_run(result.run),
            "execution": self.save_execution(run_id=run_id, execution=result.execution),
            "metrics": self.save_metrics(run_id=run_id, metrics=result.metrics),
            "benchmark": benchmark_paths,
        }

    def list_run_ids(self) -> list[str]:
        runs_dir = self.base_dir / "runs"
        if not runs_dir.exists():
            return []

        run_ids = [
            path.name
            for path in runs_dir.iterdir()
            if path.is_dir() and (path / "run.json").exists()
        ]
        return sorted(run_ids)

    def save_manifest(self, manifest: RunManifest) -> Path:
        directory = self._run_dir(manifest.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "manifest.json"
        path.write_text(
            json.dumps(_json_ready(asdict(manifest)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_manifest(self, run_id: str) -> RunManifest:
        payload = self._read_json(self._run_dir(run_id) / "manifest.json")
        payload["created_at"] = _parse_iso_datetime(payload["created_at"])
        return RunManifest(**payload)

    def save_run(self, run: BacktestRun) -> Path:
        directory = self._run_dir(run.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "run.json"
        path.write_text(
            json.dumps(_json_ready(asdict(run)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_run(self, run_id: str) -> BacktestRun:
        payload = self._read_json(self._run_dir(run_id) / "run.json")
        payload["status"] = TaskStatus(payload["status"])
        payload["created_at"] = _parse_iso_datetime(payload["created_at"])
        if payload.get("failure_code"):
            payload["failure_code"] = FailureCode(payload["failure_code"])
        return BacktestRun(**payload)

    def save_execution(self, *, run_id: str, execution: ExecutionResult) -> dict[str, Path]:
        directory = self._execution_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)

        orders_path = directory / "orders.csv"
        with orders_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "order_id",
                    "run_id",
                    "signal_id",
                    "symbol",
                    "side",
                    "order_type",
                    "qty",
                    "request_time",
                    "request_price",
                    "status",
                    "reject_reason_code",
                    "reject_payload",
                ],
            )
            writer.writeheader()
            for order in execution.orders:
                writer.writerow(
                    {
                        "order_id": order.order_id,
                        "run_id": order.run_id,
                        "signal_id": order.signal_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "order_type": order.order_type,
                        "qty": order.qty,
                        "request_time": order.request_time.isoformat(),
                        "request_price": _csv_optional_float(order.request_price),
                        "status": order.status,
                        "reject_reason_code": _csv_optional_enum(order.reject_reason_code),
                        "reject_payload": json.dumps(_json_ready(order.reject_payload), sort_keys=True),
                    }
                )

        fills_path = directory / "fills.csv"
        with fills_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "fill_id",
                    "run_id",
                    "order_id",
                    "trade_id",
                    "fill_time",
                    "fill_price",
                    "qty",
                    "fee",
                    "slippage_cost",
                ],
            )
            writer.writeheader()
            for fill in execution.fills:
                writer.writerow(
                    {
                        "fill_id": fill.fill_id,
                        "run_id": fill.run_id,
                        "order_id": fill.order_id,
                        "trade_id": fill.trade_id or "",
                        "fill_time": fill.fill_time.isoformat(),
                        "fill_price": fill.fill_price,
                        "qty": fill.qty,
                        "fee": fill.fee,
                        "slippage_cost": fill.slippage_cost,
                    }
                )

        trades_path = directory / "trades.csv"
        with trades_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "trade_id",
                    "run_id",
                    "symbol",
                    "side",
                    "entry_time",
                    "entry_price",
                    "exit_time",
                    "exit_price",
                    "qty",
                    "gross_pnl",
                    "fee",
                    "net_pnl",
                    "return_pct",
                    "holding_bars",
                    "entry_reason",
                    "exit_reason",
                ],
            )
            writer.writeheader()
            for trade in execution.trades:
                writer.writerow(
                    {
                        "trade_id": trade.trade_id,
                        "run_id": trade.run_id,
                        "symbol": trade.symbol,
                        "side": trade.side.value,
                        "entry_time": trade.entry_time.isoformat(),
                        "entry_price": trade.entry_price,
                        "exit_time": trade.exit_time.isoformat() if trade.exit_time is not None else "",
                        "exit_price": _csv_optional_float(trade.exit_price),
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

        equity_path = directory / "equity_curve.csv"
        with equity_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "cash", "used_margin", "equity", "unrealized_pnl"],
            )
            writer.writeheader()
            for point in execution.equity_curve:
                writer.writerow(
                    {
                        "timestamp": point.timestamp.isoformat(),
                        "cash": point.cash,
                        "used_margin": point.used_margin,
                        "equity": point.equity,
                        "unrealized_pnl": point.unrealized_pnl,
                    }
                )

        warnings_path = directory / "warnings.json"
        warnings_path.write_text(
            json.dumps(_json_ready([asdict(warning) for warning in execution.warnings]), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        account_path = directory / "account.json"
        account_path.write_text(
            json.dumps(_json_ready(asdict(execution.account)), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return {
            "orders": orders_path,
            "fills": fills_path,
            "trades": trades_path,
            "equity_curve": equity_path,
            "warnings": warnings_path,
            "account": account_path,
        }

    def load_execution(self, run_id: str) -> ExecutionResult:
        directory = self._execution_dir(run_id)
        orders = self._load_orders(directory / "orders.csv")
        fills = self._load_fills(directory / "fills.csv")
        trades = self._load_trades(directory / "trades.csv")
        equity_curve = self._load_equity_curve(directory / "equity_curve.csv")
        warnings = self._load_warnings(directory / "warnings.json")
        account_payload = self._read_json(directory / "account.json")
        account = AccountSnapshot(**account_payload)
        return ExecutionResult(
            orders=orders,
            fills=fills,
            trades=trades,
            warnings=warnings,
            equity_curve=equity_curve,
            account=account,
        )

    def save_metrics(self, *, run_id: str, metrics: RunMetrics) -> Path:
        directory = self._run_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "metrics.json"
        path.write_text(
            json.dumps(_json_ready(metrics.as_dict()), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_metrics(self, run_id: str) -> RunMetrics:
        payload = self._read_json(self._run_dir(run_id) / "metrics.json")
        return RunMetrics(**payload)

    def save_benchmark(self, *, run_id: str, output: BuyAndHoldBenchmarkOutput) -> dict[str, Path]:
        directory = self._benchmark_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)

        result_path = directory / "result.json"
        result_path.write_text(
            json.dumps(_json_ready(asdict(output.result)), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        equity_path = directory / "equity_points.csv"
        with equity_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "equity", "return_pct", "drawdown"],
            )
            writer.writeheader()
            for point in output.equity_points:
                writer.writerow(
                    {
                        "timestamp": point.timestamp.isoformat(),
                        "equity": point.equity,
                        "return_pct": point.return_pct,
                        "drawdown": point.drawdown,
                    }
                )

        daily_returns_path = directory / "daily_returns.csv"
        with daily_returns_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "return_pct"])
            writer.writeheader()
            for point in output.daily_returns:
                writer.writerow({"date": point.date, "return_pct": point.return_pct})

        return {
            "result": result_path,
            "equity_points": equity_path,
            "daily_returns": daily_returns_path,
        }

    def load_benchmark(self, run_id: str) -> BuyAndHoldBenchmarkOutput | None:
        directory = self._benchmark_dir(run_id)
        result_path = directory / "result.json"
        if not result_path.exists():
            return None

        payload = self._read_json(result_path)
        result = BenchmarkResult(**payload)
        equity_points = self._load_benchmark_equity_points(directory / "equity_points.csv")
        daily_returns = self._load_benchmark_daily_returns(directory / "daily_returns.csv")
        return BuyAndHoldBenchmarkOutput(
            result=result,
            equity_points=tuple(equity_points),
            daily_returns=tuple(daily_returns),
        )

    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / "runs" / run_id

    def _execution_dir(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "execution"

    def _benchmark_dir(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "benchmark"

    def _read_json(self, path: Path) -> dict[str, object] | list[dict[str, object]]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_orders(self, path: Path) -> list[OrderRequest]:
        rows = self._load_csv_rows(path)
        return [
            OrderRequest(
                order_id=row["order_id"],
                run_id=row["run_id"],
                signal_id=row["signal_id"],
                symbol=row["symbol"],
                side=Side(row["side"]),
                order_type=row["order_type"],
                qty=float(row["qty"]),
                request_time=_parse_iso_datetime(row["request_time"]),
                request_price=_load_float_or_none(row["request_price"]),
                status=row["status"],
                reject_reason_code=_load_optional_enum(RejectReasonCode, row["reject_reason_code"]),
                reject_payload=json.loads(row["reject_payload"]),
            )
            for row in rows
        ]

    def _load_fills(self, path: Path) -> list[FillEvent]:
        rows = self._load_csv_rows(path)
        return [
            FillEvent(
                fill_id=row["fill_id"],
                run_id=row["run_id"],
                order_id=row["order_id"],
                trade_id=row["trade_id"] or None,
                fill_time=_parse_iso_datetime(row["fill_time"]),
                fill_price=float(row["fill_price"]),
                qty=float(row["qty"]),
                fee=float(row["fee"]),
                slippage_cost=float(row["slippage_cost"]),
            )
            for row in rows
        ]

    def _load_trades(self, path: Path) -> list[TradeRecord]:
        rows = self._load_csv_rows(path)
        return [
            TradeRecord(
                trade_id=row["trade_id"],
                run_id=row["run_id"],
                symbol=row["symbol"],
                side=Side(row["side"]),
                entry_time=_parse_iso_datetime(row["entry_time"]),
                entry_price=float(row["entry_price"]),
                exit_time=_load_datetime_or_none(row["exit_time"]),
                exit_price=_load_float_or_none(row["exit_price"]),
                qty=float(row["qty"]),
                gross_pnl=float(row["gross_pnl"]),
                fee=float(row["fee"]),
                net_pnl=float(row["net_pnl"]),
                return_pct=float(row["return_pct"]),
                holding_bars=int(row["holding_bars"]),
                entry_reason=row["entry_reason"],
                exit_reason=row["exit_reason"],
            )
            for row in rows
        ]

    def _load_equity_curve(self, path: Path) -> list[EquityPoint]:
        rows = self._load_csv_rows(path)
        return [
            EquityPoint(
                timestamp=_parse_iso_datetime(row["timestamp"]),
                cash=float(row["cash"]),
                used_margin=float(row["used_margin"]),
                equity=float(row["equity"]),
                unrealized_pnl=float(row["unrealized_pnl"]),
            )
            for row in rows
        ]

    def _load_warnings(self, path: Path) -> list[StructuredWarning]:
        payload = self._read_json(path)
        if not isinstance(payload, list):
            raise ValueError("warnings.json must contain a list")
        warnings: list[StructuredWarning] = []
        for item in payload:
            entry = dict(item)
            entry["warning_type"] = WarningType(entry["warning_type"])
            entry["created_at"] = _parse_iso_datetime(entry["created_at"])
            warnings.append(StructuredWarning(**entry))
        return warnings

    def _load_benchmark_equity_points(self, path: Path) -> list[BenchmarkEquityPoint]:
        rows = self._load_csv_rows(path)
        return [
            BenchmarkEquityPoint(
                timestamp=_parse_iso_datetime(row["timestamp"]),
                equity=float(row["equity"]),
                return_pct=float(row["return_pct"]),
                drawdown=float(row["drawdown"]),
            )
            for row in rows
        ]

    def _load_benchmark_daily_returns(self, path: Path) -> list[BenchmarkDailyReturn]:
        rows = self._load_csv_rows(path)
        return [
            BenchmarkDailyReturn(
                date=row["date"],
                return_pct=float(row["return_pct"]),
            )
            for row in rows
        ]

    def _load_csv_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"{path.name} is missing a header row")
            return [dict(row) for row in reader]


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


EnumT = TypeVar("EnumT")


def _load_optional_enum(enum_cls: type[EnumT], value: str) -> EnumT | None:
    if not value:
        return None
    return enum_cls(value)


def _load_float_or_none(value: str) -> float | None:
    if value == "":
        return None
    return float(value)


def _load_datetime_or_none(value: str) -> datetime | None:
    if value == "":
        return None
    return _parse_iso_datetime(value)


def _csv_optional_float(value: float | None) -> str:
    return "" if value is None else str(value)


def _csv_optional_enum(value: object | None) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return getattr(value, "value")
    return str(value)
