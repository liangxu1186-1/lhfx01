"""Minimal HTTP API for the React workbench."""

from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from crypto_backtest_workbench.app.readmodels import (
    build_workspace_datasets,
    build_workspace_overview,
    build_workspace_parameter_lab,
    build_workspace_run_detail,
    build_workspace_run_index,
    build_workspace_snapshot,
    build_workspace_source,
    json_ready,
)
from crypto_backtest_workbench.app.workflows import (
    RunBacktestWorkflowRequest,
    ingest_dataset_workflow,
    run_backtest_task_workflow,
)
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileFeatureRepository,
    FileRunRepository,
)


class WorkspaceApiServer(ThreadingHTTPServer):
    """HTTP server carrying repository and data directory context."""

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        repository_root: Path,
        data_dir: Path,
        cors_origin: str,
        frontend_dist_dir: Path | None = None,
    ) -> None:
        self.repository_root = repository_root
        self.data_dir = data_dir
        self.cors_origin = cors_origin
        self.frontend_dist_dir = frontend_dist_dir
        super().__init__(server_address, WorkspaceApiHandler)

    def server_bind(self) -> None:
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class WorkspaceApiHandler(BaseHTTPRequestHandler):
    """Serve workspace readmodels and minimal workflow actions."""

    server: WorkspaceApiServer
    server_version = "CBWWorkspaceApi/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._write_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/datasets":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        datasets=build_workspace_datasets(data_dir=self.server.data_dir),
                    ),
                )
                return
            if path == "/api/overview":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        overview=build_workspace_overview(data_dir=self.server.data_dir),
                    ),
                )
                return
            if path == "/api/runs":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        runs=build_workspace_run_index(data_dir=self.server.data_dir),
                    ),
                )
                return
            if path.startswith("/api/runs/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        run=build_workspace_run_detail(
                            data_dir=self.server.data_dir,
                            run_id=unquote(path.removeprefix("/api/runs/")),
                        ),
                    ),
                )
                return
            if path == "/api/parameters":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_lab=build_workspace_parameter_lab(data_dir=self.server.data_dir),
                    ),
                )
                return
            if path == "/api/workspace":
                self._send_json(
                    HTTPStatus.OK,
                    build_workspace_snapshot(data_dir=self.server.data_dir),
                )
                return
            if self.server.frontend_dist_dir is not None:
                self._serve_frontend_asset(path)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Unknown endpoint: {path}"}})
        except Exception as exc:  # pragma: no cover - defensive fallback
            self._send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._read_json_body()
            if path == "/api/ingest":
                self._send_json(HTTPStatus.OK, self._handle_ingest(payload))
                return
            if path == "/api/run-ema":
                status, body = self._handle_run_ema(payload)
                self._send_json(status, body)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Unknown endpoint: {path}"}})
        except Exception as exc:
            self._send_error_json(exc)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _handle_ingest(self, payload: dict[str, object]) -> dict[str, object]:
        result = ingest_dataset_workflow(
            exchange=_require_str(payload, "exchange"),
            symbol=_require_str(payload, "symbol"),
            timeframe=_require_str(payload, "timeframe"),
            since=_parse_datetime(_require_str(payload, "since")),
            until=_parse_optional_datetime(payload.get("until")),
            market_type=MarketType(str(payload.get("market_type", MarketType.LINEAR_USDT_PERPETUAL.value))),
            price_type=PriceType(str(payload.get("price_type", PriceType.LAST.value))),
            repository_root=self.server.repository_root,
            data_dir=self.server.data_dir,
            limit=int(payload.get("limit", 1000)),
            drop_unclosed_last_candle=bool(payload.get("drop_unclosed_last_candle", True)),
            extra_params=_optional_dict(payload.get("extra_params")),
            exchange_options=_optional_dict(payload.get("exchange_options")),
        )
        return {
            "dataset_snapshot_id": result.snapshot.dataset_snapshot_id,
            "row_count": result.snapshot.row_count,
            "snapshot_path": str(result.snapshot_path),
            "candles_path": str(result.candles_path),
            "integrity_report_path": str(result.integrity_report_path),
            "dropped_open_candle": result.dropped_open_candle,
        }

    def _handle_run_ema(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        snapshot = _load_snapshot(self.server.data_dir, _require_str(payload, "snapshot_id"))
        validation_split = _build_validation_split(
            payload=payload,
            snapshot=snapshot,
        )

        request = RunBacktestWorkflowRequest(
            run_id=_require_str(payload, "run_id"),
            snapshot=snapshot,
            strategy_params={
                "fast_period": int(payload.get("fast_period", 2)),
                "slow_period": int(payload.get("slow_period", 3)),
                "qty_policy_ref": str(payload.get("qty_policy_ref", "fixed_notional_v1")),
            },
            constraints=ExecutionConstraints(
                initial_cash=float(payload.get("initial_cash", 10_000.0)),
                leverage=float(payload.get("leverage", 1.0)),
                fee_rate=float(payload.get("fee_rate", 0.0)),
                slippage_bps=float(payload.get("slippage_bps", 0.0)),
                min_notional=float(payload.get("min_notional", 0.0)),
                qty_by_policy={
                    str(payload.get("qty_policy_ref", "fixed_notional_v1")): float(_require_number(payload, "qty"))
                },
            ),
            validation_split=validation_split,
            enable_buy_and_hold_benchmark=str(payload.get("benchmark", "buy_and_hold")) == "buy_and_hold",
        )

        runner = LocalTaskRunner()
        dataset_repository = FileDatasetRepository(self.server.data_dir)
        feature_repository = FileFeatureRepository(self.server.data_dir)
        run_repository = FileRunRepository(self.server.data_dir)
        task_result = run_backtest_task_workflow(
            runner=runner,
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
            request=request,
        )
        task = task_result.task
        if task_result.output is None:
            return (
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "task_id": task.task_id,
                    "task_status": task.status.value,
                    "run_id": request.run_id,
                    "dataset_snapshot_id": snapshot.dataset_snapshot_id,
                    "failure_code": task.failure_code.value if task.failure_code is not None else None,
                    "failure_stage": task.failure_stage,
                    "failure_message": task.failure_message,
                },
            )

        workflow_result = task_result.output.workflow_result
        execution = workflow_result.single_run_result.execution
        metrics = workflow_result.single_run_result.metrics.as_dict()
        return (
            HTTPStatus.OK,
            {
                "task_id": task.task_id,
                "task_status": task.status.value,
                "run_id": workflow_result.single_run_result.run.run_id,
                "dataset_snapshot_id": snapshot.dataset_snapshot_id,
                "feature_artifact_id": workflow_result.feature_artifact.feature_artifact_id,
                "signal_count": len(workflow_result.signals),
                "order_count": len(execution.orders),
                "fill_count": len(execution.fills),
                "warning_count": len(execution.warnings),
                "trade_count": metrics.get("trade_count"),
                "benchmark_enabled": workflow_result.single_run_result.benchmark_output is not None,
                "validation_split_id": workflow_result.single_run_result.run.validation_split_id,
                "metrics": metrics,
                "persisted": json_ready(task_result.output.persisted_paths),
            },
        )

    def _read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, object] | list[object]) -> None:
        body = json.dumps(json_ready(payload), indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._write_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, exc: Exception) -> None:
        status = HTTPStatus.BAD_REQUEST if isinstance(exc, (ValueError, FileNotFoundError, KeyError)) else HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_json(
            status,
            {
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            },
        )

    def _build_workspace_payload(self, **sections: object) -> dict[str, object]:
        return {
            "generated_at": datetime.now(UTC),
            "source": build_workspace_source(data_dir=self.server.data_dir),
            **sections,
        }

    def _serve_frontend_asset(self, path: str) -> None:
        frontend_dist_dir = self.server.frontend_dist_dir
        if frontend_dist_dir is None:
            raise FileNotFoundError("frontend_dist_dir is not configured")

        requested = path.lstrip("/")
        asset_path = frontend_dist_dir / requested
        if path in {"", "/"}:
            asset_path = frontend_dist_dir / "index.html"
        elif requested and not asset_path.exists():
            asset_path = frontend_dist_dir / "index.html"

        if not asset_path.exists() or not asset_path.is_file():
            raise FileNotFoundError(f"Frontend asset not found: {path}")

        body = asset_path.read_bytes()
        content_type, _ = mimetypes.guess_type(asset_path.name)
        if asset_path.suffix == ".js":
            content_type = "application/javascript"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.server.cors_origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")


def create_api_server(
    *,
    host: str,
    port: int,
    repository_root: str | Path,
    data_dir: str | Path | None = None,
    cors_origin: str = "*",
    frontend_dist_dir: str | Path | None = None,
) -> WorkspaceApiServer:
    repository_root_path = Path(repository_root).resolve()
    data_dir_path = Path(data_dir).resolve() if data_dir is not None else repository_root_path / "data"
    frontend_dist_path = Path(frontend_dist_dir).resolve() if frontend_dist_dir is not None else None
    return WorkspaceApiServer(
        (host, port),
        repository_root=repository_root_path,
        data_dir=data_dir_path,
        cors_origin=cors_origin,
        frontend_dist_dir=frontend_dist_path,
    )


def serve_api(
    *,
    host: str,
    port: int,
    repository_root: str | Path,
    data_dir: str | Path | None = None,
    cors_origin: str = "*",
) -> int:
    server = create_api_server(
        host=host,
        port=port,
        repository_root=repository_root,
        data_dir=data_dir,
        cors_origin=cors_origin,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def serve_ui(
    *,
    host: str,
    port: int,
    repository_root: str | Path,
    data_dir: str | Path | None = None,
    cors_origin: str = "*",
    frontend_dist_dir: str | Path | None = None,
) -> int:
    repository_root_path = Path(repository_root).resolve()
    frontend_dist_path = (
        Path(frontend_dist_dir).resolve()
        if frontend_dist_dir is not None
        else repository_root_path / "frontend" / "dist"
    )
    index_path = frontend_dist_path / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(
            f"React build output not found at {index_path}. Run `cd frontend && npm run build` first."
        )

    server = create_api_server(
        host=host,
        port=port,
        repository_root=repository_root_path,
        data_dir=data_dir,
        cors_origin=cors_origin,
        frontend_dist_dir=frontend_dist_path,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def _load_snapshot(data_dir: Path, snapshot_id: str) -> DatasetSnapshot:
    path = data_dir / "datasets" / snapshot_id / "snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DatasetSnapshot(
        dataset_snapshot_id=payload["dataset_snapshot_id"],
        source=payload["source"],
        exchange=payload["exchange"],
        market_type=MarketType(payload["market_type"]),
        symbol=payload["symbol"],
        timeframe=payload["timeframe"],
        time_range_start=_parse_datetime(payload["time_range_start"]),
        time_range_end=_parse_datetime(payload["time_range_end"]),
        row_count=int(payload["row_count"]),
        schema_version=payload["schema_version"],
        feature_version=payload["feature_version"],
        storage_uri=payload["storage_uri"],
        created_at=_parse_datetime(payload["created_at"]),
        data_source=payload["data_source"],
        price_type=PriceType(payload.get("price_type", PriceType.LAST.value)),
    )


def _build_validation_split(
    *,
    payload: dict[str, object],
    snapshot: DatasetSnapshot,
) -> ValidationSplit | None:
    boundaries = {
        "is_start": payload.get("is_start"),
        "is_end": payload.get("is_end"),
        "oos_start": payload.get("oos_start"),
        "oos_end": payload.get("oos_end"),
    }
    provided = [name for name, value in boundaries.items() if value not in {None, ""}]
    if not provided:
        return None
    if len(provided) != len(boundaries):
        joined = ", ".join(sorted(boundaries))
        raise ValueError(f"Validation split requires all of: {joined}")

    warmup_bars = int(payload.get("warmup_bars", 0))
    if warmup_bars < 0:
        raise ValueError("warmup_bars must be >= 0")

    return ValidationSplit(
        validation_split_id=str(payload.get("validation_split_id", "validation:api")),
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id=snapshot.dataset_snapshot_id,
        warmup_bars=warmup_bars,
        is_start=_parse_datetime(str(payload["is_start"])),
        is_end=_parse_datetime(str(payload["is_end"])),
        oos_start=_parse_datetime(str(payload["oos_start"])),
        oos_end=_parse_datetime(str(payload["oos_end"])),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: object | None) -> datetime | None:
    if value in {None, ""}:
        return None
    return _parse_datetime(str(value))


def _optional_dict(value: object | None) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object payload")
    return dict(value)


def _require_str(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if value in {None, ""}:
        raise KeyError(field_name)
    return str(value)


def _require_number(payload: dict[str, object], field_name: str) -> float:
    value = payload.get(field_name)
    if value is None:
        raise KeyError(field_name)
    return float(value)
