"""Minimal HTTP API for the React workbench."""

from __future__ import annotations

import json
import mimetypes
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from crypto_backtest_workbench.app.readmodels import (
    build_workspace_datasets,
    build_workspace_overview,
    build_workspace_overview_equity,
    build_workspace_parameter_lab,
    build_workspace_run_detail,
    build_workspace_run_index,
    build_workspace_snapshot,
    build_workspace_source,
    json_ready,
)
from crypto_backtest_workbench.app.workflows import (
    ParameterExperimentBatchRequest,
    ParameterExperimentTaskRequest,
    build_parameter_experiment_batch,
    build_parameter_experiment_task,
    RunBacktestWorkflowRequest,
    ingest_dataset_workflow,
    run_parameter_experiment_batch_workflow,
    run_parameter_experiment_task_workflow,
    run_backtest_task_workflow,
)
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
    ResearchNote,
    SearchType,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileExperimentBatchRepository,
    FileParameterExperimentRepository,
    FileFeatureRepository,
    FileResearchNoteRepository,
    FileRunRepository,
    FileTaskRepository,
)

DEFAULT_QTY_POLICY_REF = "percent_of_cash"
DEFAULT_CASH_ALLOCATION_PCT = 100.0


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
        self.background_threads: dict[str, threading.Thread] = {}
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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
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
            if path == "/api/overview-equity":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        multi_run_equity=build_workspace_overview_equity(
                            data_dir=self.server.data_dir,
                            run_ids=[run_id for run_id in query.get("run_id", []) if run_id],
                        ),
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
            if path == "/api/tasks":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        tasks=self._build_task_index(),
                    ),
                )
                return
            if path == "/api/parameter-experiments":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_experiments=self._build_parameter_experiment_index(),
                    ),
                )
                return
            if path == "/api/parameter-experiment-batches":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_experiment_batches=self._build_parameter_experiment_batch_index(),
                    ),
                )
                return
            if path == "/api/research-notes":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        research_notes=self._build_research_note_index(query),
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
            if path.startswith("/api/tasks/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        task=self._build_task_detail(unquote(path.removeprefix("/api/tasks/"))),
                    ),
                )
                return
            if path.startswith("/api/parameter-experiments/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_experiment=self._build_parameter_experiment_detail(
                            unquote(path.removeprefix("/api/parameter-experiments/"))
                        ),
                    ),
                )
                return
            if path.startswith("/api/parameter-experiment-batches/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_experiment_batch=self._build_parameter_experiment_batch_detail(
                            unquote(path.removeprefix("/api/parameter-experiment-batches/"))
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
            if path == "/api/parameter-experiments":
                status, body = self._handle_parameter_experiment(payload)
                self._send_json(status, body)
                return
            if path == "/api/parameter-experiment-batches":
                status, body = self._handle_parameter_experiment_batch(payload)
                self._send_json(status, body)
                return
            if path == "/api/research-notes":
                status, body = self._handle_create_research_note(payload)
                self._send_json(status, body)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Unknown endpoint: {path}"}})
        except Exception as exc:
            self._send_error_json(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/datasets/"):
                snapshot_id = unquote(path.removeprefix("/api/datasets/"))
                self._send_json(HTTPStatus.OK, self._handle_delete_dataset(snapshot_id))
                return
            if path.startswith("/api/runs/"):
                run_id = unquote(path.removeprefix("/api/runs/"))
                self._send_json(HTTPStatus.OK, self._handle_delete_run(run_id))
                return
            if path.startswith("/api/parameter-experiment-batches/"):
                batch_id = unquote(path.removeprefix("/api/parameter-experiment-batches/"))
                self._send_json(HTTPStatus.OK, self._handle_delete_parameter_experiment_batch(batch_id))
                return
            if path.startswith("/api/parameter-experiments/"):
                experiment_id = unquote(path.removeprefix("/api/parameter-experiments/"))
                self._send_json(HTTPStatus.OK, self._handle_delete_parameter_experiment(experiment_id))
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
        qty_policy_ref, constraints = _build_execution_constraints(payload)

        request = RunBacktestWorkflowRequest(
            run_id=_require_str(payload, "run_id"),
            snapshot=snapshot,
            strategy_params={
                "fast_period": int(payload.get("fast_period", 2)),
                "slow_period": int(payload.get("slow_period", 3)),
                "qty_policy_ref": qty_policy_ref,
            },
            constraints=constraints,
            validation_split=validation_split,
            enable_buy_and_hold_benchmark=str(payload.get("benchmark", "buy_and_hold")) == "buy_and_hold",
        )

        runner = LocalTaskRunner()
        dataset_repository = FileDatasetRepository(self.server.data_dir)
        feature_repository = FileFeatureRepository(self.server.data_dir)
        run_repository = FileRunRepository(self.server.data_dir)
        task_repository = FileTaskRepository(self.server.data_dir)
        task_result = run_backtest_task_workflow(
            runner=runner,
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
            request=request,
        )
        task = task_result.task
        task_repository.save_task(task)
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

    def _build_task_index(self) -> list[dict[str, object]]:
        task_repository = FileTaskRepository(self.server.data_dir)
        return [json_ready(task) for task in task_repository.list_tasks()]

    def _build_task_detail(self, task_id: str) -> dict[str, object]:
        task_repository = FileTaskRepository(self.server.data_dir)
        return json_ready(task_repository.load_task(task_id))

    def _build_parameter_experiment_index(self) -> list[dict[str, object]]:
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        payloads: list[dict[str, object]] = []
        for experiment_id in experiment_repository.list_experiment_ids():
            experiment = experiment_repository.load_experiment(experiment_id)
            execution = experiment_repository.load_execution_index(experiment_id)
            payloads.append(
                {
                    "experiment_id": experiment.experiment_id,
                    "strategy_name": experiment.strategy_name,
                    "dataset_bundle_id": experiment.dataset_bundle_id,
                    "search_type": experiment.search_type.value,
                    "task_id": execution.get("task_id"),
                    "status": execution.get("status", "pending"),
                    "planned_run_count": execution.get("planned_run_count", len(execution.get("run_ids", []))),
                    "run_count": len(execution.get("run_ids", [])),
                    "failed_run_count": len(execution.get("failed_child_task_ids", [])),
                    "created_at": experiment.created_at,
                }
            )
        return payloads

    def _build_parameter_experiment_detail(self, experiment_id: str) -> dict[str, object]:
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        return {
            "experiment": json_ready(experiment_repository.load_experiment(experiment_id)),
            "execution": experiment_repository.load_execution_index(experiment_id),
        }

    def _build_parameter_experiment_batch_index(self) -> list[dict[str, object]]:
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        payloads: list[dict[str, object]] = []
        for batch_id in batch_repository.list_batch_ids():
            batch = batch_repository.load_batch(batch_id)
            execution = batch_repository.load_execution_index(batch_id)
            payloads.append(
                {
                    "batch_id": batch.batch_id,
                    "strategy_name": batch.strategy_name,
                    "snapshot_count": len(batch.dataset_snapshot_ids),
                    "experiment_count": len(batch.experiment_ids),
                    "search_type": batch.search_type.value,
                    "task_id": execution.get("task_id"),
                    "status": execution.get("status", "pending"),
                    "planned_experiment_count": execution.get("planned_experiment_count", len(batch.experiment_ids)),
                    "planned_run_count": execution.get("planned_run_count", len(execution.get("run_ids", []))),
                    "run_count": len(execution.get("run_ids", [])),
                    "failed_experiment_count": len(execution.get("failed_experiment_ids", [])),
                    "created_at": batch.created_at,
                }
            )
        return payloads

    def _build_parameter_experiment_batch_detail(self, batch_id: str) -> dict[str, object]:
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        batch = batch_repository.load_batch(batch_id)
        execution = batch_repository.load_execution_index(batch_id)
        experiments: list[dict[str, object]] = []
        for experiment_id in batch.experiment_ids:
            try:
                experiment = experiment_repository.load_experiment(experiment_id)
                experiment_execution = experiment_repository.load_execution_index(experiment_id)
            except FileNotFoundError:
                experiments.append(
                    {
                        "experiment": {"experiment_id": experiment_id},
                        "execution": {},
                    }
                )
                continue
            experiments.append(
                {
                    "experiment": json_ready(experiment),
                    "execution": experiment_execution,
                }
            )

        run_ids = set(str(run_id) for run_id in execution.get("run_ids", []))
        summaries = build_workspace_run_index(data_dir=self.server.data_dir)
        run_rows = [row for row in summaries if row["run_id"] in run_ids]
        parameter_groups, recommendations, scoring_rules = _build_batch_recommendations(run_rows)
        return {
            "batch": json_ready(batch),
            "execution": execution,
            "experiments": experiments,
            "run_rows": run_rows,
            "parameter_groups": parameter_groups,
            "recommendations": recommendations,
            "scoring_rules": scoring_rules,
        }

    def _build_research_note_index(self, query: dict[str, list[str]]) -> list[dict[str, object]]:
        repository = FileResearchNoteRepository(self.server.data_dir)
        target_type = _first_query_value(query, "target_type")
        target_id = _first_query_value(query, "target_id")
        return [json_ready(note) for note in repository.list_notes(target_type=target_type, target_id=target_id)]

    def _handle_parameter_experiment(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        snapshot = _load_snapshot(self.server.data_dir, _require_str(payload, "snapshot_id"))
        experiment_id = _require_str(payload, "experiment_id")
        qty_policy_ref = _resolve_qty_policy_ref(payload)
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        if experiment_id in experiment_repository.list_experiment_ids():
            raise FileExistsError(f"Parameter experiment already exists: {experiment_id}")
        request = ParameterExperimentTaskRequest(
            experiment_id=experiment_id,
            snapshot=snapshot,
            search_type=SearchType(str(payload.get("search_type", SearchType.GRID.value))),
            fast_periods=_require_int_tuple(payload, "fast_periods"),
            slow_periods=_require_int_tuple(payload, "slow_periods"),
            qty_policy_ref=qty_policy_ref,
            qty=_optional_number(payload.get("qty")),
            cash_allocation_pct=_optional_number(
                payload.get("cash_allocation_pct"),
                default=DEFAULT_CASH_ALLOCATION_PCT if qty_policy_ref == DEFAULT_QTY_POLICY_REF else None,
            ),
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=_require_float_tuple(payload, "leverage_candidates", fallback_field_name="leverage"),
            fee_rate=float(payload.get("fee_rate", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            min_notional=float(payload.get("min_notional", 0.0)),
            benchmark_enabled=str(payload.get("benchmark", "buy_and_hold")) == "buy_and_hold",
            max_samples=int(payload["max_samples"]) if payload.get("max_samples") is not None else None,
            seed=int(payload["seed"]) if payload.get("seed") is not None else None,
            validation_split=_build_validation_split(payload=payload, snapshot=snapshot),
        )
        task, experiment, combinations = build_parameter_experiment_task(request)
        task_repository = FileTaskRepository(self.server.data_dir)
        task_repository.save_task(task)
        experiment_repository.save_experiment(experiment)
        experiment_repository.save_execution_index(
            experiment_id,
            {
                "experiment_id": experiment_id,
                "task_id": task.task_id,
                "status": task.status.value,
                "run_ids": [],
                "child_task_ids": [],
                "failed_child_task_ids": [],
                "planned_run_count": len(combinations),
                "updated_at": task.updated_at.isoformat(),
            },
        )

        worker = threading.Thread(
            target=self._run_parameter_experiment_in_background,
            args=(request,),
            daemon=True,
            name=f"parameter-experiment:{experiment_id}",
        )
        self.server.background_threads[task.task_id] = worker
        worker.start()
        return (
            HTTPStatus.ACCEPTED,
            {
                "task_id": task.task_id,
                "task_status": task.status.value,
                "experiment_id": experiment_id,
                "search_type": request.search_type.value,
                "planned_run_count": len(combinations),
            },
        )

    def _handle_parameter_experiment_batch(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        batch_id = _require_str(payload, "batch_id")
        snapshot_ids = _require_str_list(payload, "snapshot_ids")
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        if batch_id in batch_repository.list_batch_ids():
            raise FileExistsError(f"Parameter experiment batch already exists: {batch_id}")
        snapshots = tuple(_load_snapshot(self.server.data_dir, snapshot_id) for snapshot_id in snapshot_ids)
        qty_policy_ref = _resolve_qty_policy_ref(payload)
        request = ParameterExperimentBatchRequest(
            batch_id=batch_id,
            snapshots=snapshots,
            search_type=SearchType(str(payload.get("search_type", SearchType.GRID.value))),
            fast_periods=_require_int_tuple(payload, "fast_periods"),
            slow_periods=_require_int_tuple(payload, "slow_periods"),
            qty_policy_ref=qty_policy_ref,
            qty=_optional_number(payload.get("qty")),
            cash_allocation_pct=_optional_number(
                payload.get("cash_allocation_pct"),
                default=DEFAULT_CASH_ALLOCATION_PCT if qty_policy_ref == DEFAULT_QTY_POLICY_REF else None,
            ),
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=_require_float_tuple(payload, "leverage_candidates", fallback_field_name="leverage"),
            fee_rate=float(payload.get("fee_rate", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            min_notional=float(payload.get("min_notional", 0.0)),
            benchmark_enabled=str(payload.get("benchmark", "buy_and_hold")) == "buy_and_hold",
            max_samples=int(payload["max_samples"]) if payload.get("max_samples") is not None else None,
            seed=int(payload["seed"]) if payload.get("seed") is not None else None,
        )
        task, batch, child_requests, planned_run_count = build_parameter_experiment_batch(request)
        task_repository = FileTaskRepository(self.server.data_dir)
        task_repository.save_task(task)
        batch_repository.save_batch(batch)
        batch_repository.save_execution_index(
            batch_id,
            {
                "batch_id": batch_id,
                "task_id": task.task_id,
                "status": task.status.value,
                "dataset_snapshot_ids": list(batch.dataset_snapshot_ids),
                "experiment_ids": list(batch.experiment_ids),
                "run_ids": [],
                "child_task_ids": [],
                "failed_experiment_ids": [],
                "planned_experiment_count": len(child_requests),
                "planned_run_count": planned_run_count,
                "updated_at": task.updated_at.isoformat(),
            },
        )
        worker = threading.Thread(
            target=self._run_parameter_experiment_batch_in_background,
            args=(request,),
            daemon=True,
            name=f"parameter-experiment-batch:{batch_id}",
        )
        self.server.background_threads[task.task_id] = worker
        worker.start()
        return (
            HTTPStatus.ACCEPTED,
            {
                "task_id": task.task_id,
                "task_status": task.status.value,
                "batch_id": batch_id,
                "search_type": request.search_type.value,
                "planned_experiment_count": len(child_requests),
                "planned_run_count": planned_run_count,
            },
        )

    def _run_parameter_experiment_in_background(self, request: ParameterExperimentTaskRequest) -> None:
        run_parameter_experiment_task_workflow(
            request=request,
            task_repository=FileTaskRepository(self.server.data_dir),
            experiment_repository=FileParameterExperimentRepository(self.server.data_dir),
            dataset_repository=FileDatasetRepository(self.server.data_dir),
            feature_repository=FileFeatureRepository(self.server.data_dir),
            run_repository=FileRunRepository(self.server.data_dir),
        )

    def _run_parameter_experiment_batch_in_background(self, request: ParameterExperimentBatchRequest) -> None:
        run_parameter_experiment_batch_workflow(
            request=request,
            task_repository=FileTaskRepository(self.server.data_dir),
            batch_repository=FileExperimentBatchRepository(self.server.data_dir),
            experiment_repository=FileParameterExperimentRepository(self.server.data_dir),
            dataset_repository=FileDatasetRepository(self.server.data_dir),
            feature_repository=FileFeatureRepository(self.server.data_dir),
            run_repository=FileRunRepository(self.server.data_dir),
        )

    def _handle_create_research_note(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        target_type = _require_str(payload, "target_type")
        target_id = _require_str(payload, "target_id")
        _validate_research_note_target(self.server.data_dir, target_type=target_type, target_id=target_id)
        content = _require_str(payload, "content").strip()
        if not content:
            raise ValueError("content must not be empty")
        labels = _normalize_labels(payload.get("labels"))
        author = str(payload.get("author", "local")).strip() or "local"
        note_id = str(payload.get("note_id", _build_research_note_id()))
        repository = FileResearchNoteRepository(self.server.data_dir)
        if note_id in repository.list_note_ids():
            raise FileExistsError(f"Research note already exists: {note_id}")
        note = ResearchNote(
            note_id=note_id,
            target_type=target_type,
            target_id=target_id,
            content=content,
            author=author,
            labels=labels,
        )
        repository.save_note(note)
        return (
            HTTPStatus.CREATED,
            {
                "note": json_ready(note),
            },
        )

    def _handle_delete_run(self, run_id: str) -> dict[str, object]:
        run_repository = FileRunRepository(self.server.data_dir)
        run_repository.delete_run(run_id)
        FileResearchNoteRepository(self.server.data_dir).delete_notes(target_type="run", target_id=run_id)
        experiment_ids, batch_ids = self._prune_deleted_run_from_parameter_indexes(run_id)
        return {
            "run_id": run_id,
            "deleted": True,
            "experiment_ids": experiment_ids,
            "batch_ids": batch_ids,
        }

    def _handle_delete_parameter_experiment(self, experiment_id: str) -> dict[str, object]:
        deleted = self._delete_parameter_experiment_resources(experiment_id)
        deleted["deleted"] = True
        return deleted

    def _handle_delete_parameter_experiment_batch(self, batch_id: str) -> dict[str, object]:
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        task_repository = FileTaskRepository(self.server.data_dir)
        batch = batch_repository.load_batch(batch_id)
        execution = batch_repository.load_execution_index(batch_id)

        deleted_run_ids: set[str] = set()
        deleted_task_ids: set[str] = set()
        deleted_experiment_ids: list[str] = []
        for experiment_id in batch.experiment_ids:
            deleted = self._delete_parameter_experiment_resources(experiment_id, ignore_missing=True)
            deleted_experiment_ids.append(experiment_id)
            deleted_run_ids.update(str(run_id) for run_id in deleted.get("run_ids", []))
            deleted_task_ids.update(str(task_id) for task_id in deleted.get("task_ids", []))

        batch_task_ids = {
            str(task_id)
            for task_id in [execution.get("task_id"), *execution.get("child_task_ids", [])]
            if task_id
        }
        for task_id in batch_task_ids:
            if task_id in deleted_task_ids:
                continue
            _delete_task_if_exists(task_repository, task_id)
            deleted_task_ids.add(task_id)

        note_repository = FileResearchNoteRepository(self.server.data_dir)
        note_repository.delete_notes(target_type="parameter_experiment_batch", target_id=batch_id)
        for note in note_repository.list_notes(target_type="parameter_group"):
            if note.target_id.startswith(f"{batch_id}:"):
                note_repository.delete_note(note.note_id)

        batch_repository.delete_batch(batch_id)
        return {
            "batch_id": batch_id,
            "deleted": True,
            "experiment_ids": deleted_experiment_ids,
            "run_ids": sorted(deleted_run_ids),
            "task_ids": sorted(deleted_task_ids),
            "snapshot_ids": list(batch.dataset_snapshot_ids),
        }

    def _handle_delete_dataset(self, snapshot_id: str) -> dict[str, object]:
        dataset_repository = FileDatasetRepository(self.server.data_dir)
        dataset_repository.delete_snapshot(snapshot_id)
        return {
            "dataset_snapshot_id": snapshot_id,
            "deleted": True,
        }

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
        if isinstance(exc, FileNotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, FileExistsError):
            status = HTTPStatus.CONFLICT
        elif isinstance(exc, (ValueError, KeyError)):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    def _delete_parameter_experiment_resources(
        self,
        experiment_id: str,
        *,
        ignore_missing: bool = False,
    ) -> dict[str, object]:
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        run_repository = FileRunRepository(self.server.data_dir)
        task_repository = FileTaskRepository(self.server.data_dir)
        note_repository = FileResearchNoteRepository(self.server.data_dir)

        try:
            execution = experiment_repository.load_execution_index(experiment_id)
        except FileNotFoundError:
            if ignore_missing:
                return {"experiment_id": experiment_id, "run_ids": [], "task_ids": []}
            raise

        run_ids = [str(run_id) for run_id in execution.get("run_ids", [])]
        task_ids = {
            str(task_id)
            for task_id in [
                execution.get("task_id"),
                *execution.get("child_task_ids", []),
                *execution.get("failed_child_task_ids", []),
            ]
            if task_id
        }

        for run_id in run_ids:
            _delete_run_if_exists(run_repository, run_id)
            note_repository.delete_notes(target_type="run", target_id=run_id)

        note_repository.delete_notes(target_type="parameter_experiment", target_id=experiment_id)

        for task_id in task_ids:
            _delete_task_if_exists(task_repository, task_id)

        try:
            experiment_repository.delete_experiment(experiment_id)
        except FileNotFoundError:
            if not ignore_missing:
                raise

        return {
            "experiment_id": experiment_id,
            "run_ids": run_ids,
            "task_ids": sorted(task_ids),
        }

    def _prune_deleted_run_from_parameter_indexes(self, run_id: str) -> tuple[list[str], list[str]]:
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)

        changed_experiment_ids: list[str] = []
        for experiment_id in experiment_repository.list_experiment_ids():
            execution = experiment_repository.load_execution_index(experiment_id)
            run_ids = [str(value) for value in execution.get("run_ids", [])]
            if run_id not in run_ids:
                continue
            execution["run_ids"] = [value for value in run_ids if value != run_id]
            experiment_repository.save_execution_index(experiment_id, execution)
            changed_experiment_ids.append(experiment_id)

        changed_batch_ids: list[str] = []
        for batch_id in batch_repository.list_batch_ids():
            execution = batch_repository.load_execution_index(batch_id)
            run_ids = [str(value) for value in execution.get("run_ids", [])]
            if run_id not in run_ids:
                continue
            execution["run_ids"] = [value for value in run_ids if value != run_id]
            batch_repository.save_execution_index(batch_id, execution)
            changed_batch_ids.append(batch_id)

        return changed_experiment_ids, changed_batch_ids


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
    _print_startup_banner(server=server, mode="api")
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
    _print_startup_banner(server=server, mode="ui")
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


def _print_startup_banner(*, server: WorkspaceApiServer, mode: str) -> None:
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    base_url = f"http://{host}:{port}"
    print("=== CBW STARTED ===")
    print(f"status: 启动成功")
    print(f"mode: {mode}")
    print(f"url: {base_url}")
    print(f"health: {base_url}/api/health")
    if mode == "ui":
        print(f"ui: {base_url}/")
    print(f"data_dir: {server.data_dir}")
    print(f"repository_root: {server.repository_root}")


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


def _optional_number(value: object | None, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("Expected number, got boolean")
    return float(value)


def _resolve_qty_policy_ref(payload: dict[str, object]) -> str:
    return str(payload.get("qty_policy_ref", DEFAULT_QTY_POLICY_REF))


def _build_execution_constraints(payload: dict[str, object]) -> tuple[str, ExecutionConstraints]:
    qty_policy_ref = _resolve_qty_policy_ref(payload)
    qty = _optional_number(payload.get("qty"))
    cash_allocation_pct = _optional_number(payload.get("cash_allocation_pct"))
    qty_by_policy: dict[str, float] = {}
    cash_allocation_pct_by_policy: dict[str, float] = {}

    if cash_allocation_pct is not None:
        if qty_policy_ref != DEFAULT_QTY_POLICY_REF:
            raise ValueError("cash_allocation_pct only supports qty_policy_ref=percent_of_cash")
        cash_allocation_pct_by_policy[qty_policy_ref] = cash_allocation_pct
    elif qty is not None:
        qty_by_policy[qty_policy_ref] = qty
    elif qty_policy_ref == DEFAULT_QTY_POLICY_REF:
        cash_allocation_pct_by_policy[qty_policy_ref] = DEFAULT_CASH_ALLOCATION_PCT
    else:
        raise KeyError("Either qty or cash_allocation_pct must be provided")

    return (
        qty_policy_ref,
        ExecutionConstraints(
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage=float(payload.get("leverage", 1.0)),
            fee_rate=float(payload.get("fee_rate", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            min_notional=float(payload.get("min_notional", 0.0)),
            qty_by_policy=qty_by_policy,
            cash_allocation_pct_by_policy=cash_allocation_pct_by_policy,
        ),
    )


def _require_int_tuple(payload: dict[str, object], field_name: str) -> tuple[int, ...]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    return tuple(int(item) for item in value)


def _require_float_tuple(payload: dict[str, object], field_name: str, *, fallback_field_name: str | None = None) -> tuple[float, ...]:
    value = payload.get(field_name)
    if value is None and fallback_field_name is not None:
        fallback = payload.get(fallback_field_name, 1.0)
        return (float(fallback),)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    return tuple(float(item) for item in value)


def _require_str_list(payload: dict[str, object], field_name: str) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise ValueError(f"{field_name} must be a non-empty array")
    return items


def _first_query_value(query: dict[str, list[str]], field_name: str) -> str | None:
    values = query.get(field_name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _normalize_labels(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("labels must be an array")
    labels = tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    return labels


def _build_research_note_id() -> str:
    return f"note-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"


def _validate_research_note_target(data_dir: Path, *, target_type: str, target_id: str) -> None:
    if target_type == "run":
        _ = FileRunRepository(data_dir).load_run(target_id)
        return
    if target_type == "parameter_experiment":
        _ = FileParameterExperimentRepository(data_dir).load_experiment(target_id)
        return
    if target_type == "parameter_experiment_batch":
        _ = FileExperimentBatchRepository(data_dir).load_batch(target_id)
        return
    if target_type == "parameter_group":
        batch_id = target_id.split(":", 1)[0].strip()
        if not batch_id:
            raise ValueError("parameter_group target_id must start with batch_id")
        _ = FileExperimentBatchRepository(data_dir).load_batch(batch_id)
        return
    raise ValueError("target_type must be one of run, parameter_experiment, parameter_experiment_batch, parameter_group")


def _delete_run_if_exists(run_repository: FileRunRepository, run_id: str) -> None:
    try:
        run_repository.delete_run(run_id)
    except FileNotFoundError:
        return


def _delete_task_if_exists(task_repository: FileTaskRepository, task_id: str) -> None:
    try:
        task_repository.delete_task(task_id)
    except FileNotFoundError:
        return


BATCH_RECOMMENDATION_RULES: dict[str, dict[str, object]] = {
    "robust_candidate": {
        "label": "自动稳健候选",
        "summary": "跨多个快照样本内外都保持正收益，且相邻参数区间没有明显断层。",
        "thresholds": [
            "覆盖快照数 >= 2",
            "正收益占比 >= 60%",
            "平均收益率 > 0",
            "平均超额收益 > 0",
            "平均最大回撤 <= 35%",
            "最少交易数 >= 3",
            "相邻参数稳定度 >= 50%，且至少有 1 个稳定邻居",
            "若存在样本外数据，则平均样本外收益 > 0、平均样本外超额 > 0、样本外正收益占比 >= 50%",
        ],
        "min_snapshot_count": 2,
        "min_positive_ratio": 0.6,
        "min_trade_count": 3,
        "max_avg_drawdown": 0.35,
        "min_neighbor_stability": 0.5,
        "min_stable_neighbor_count": 1,
        "min_oos_positive_ratio": 0.5,
    },
    "high_return_candidate": {
        "label": "自动高收益候选",
        "summary": "收益上限足够高，但稳定性还没有达到稳健候选标准。",
        "thresholds": [
            "最佳收益率 > 0",
            "平均收益率 > 0",
            "未命中自动排除",
            "且未命中自动稳健候选",
        ],
    },
    "excluded_combination": {
        "label": "自动排除",
        "summary": "平均收益或样本外正收益表现明显不达标，应优先排除。",
        "thresholds": [
            "平均收益率 <= 0，或",
            "正收益占比 = 0，或",
            "最差最大回撤 >= 80%，或",
            "存在样本外数据且样本外正收益占比 = 0",
        ],
    },
}


def _build_batch_scoring_rules() -> dict[str, dict[str, object]]:
    return {
        key: {
            "label": value["label"],
            "summary": value["summary"],
            "thresholds": list(value["thresholds"]),
        }
        for key, value in BATCH_RECOMMENDATION_RULES.items()
    }


def _clamp_score(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _score_metric(value: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return _clamp_score(value / target)


def _build_batch_recommendations(
    run_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]], dict[str, dict[str, object]]]:
    grouped: dict[tuple[int | None, int | None, float | None], dict[str, object]] = {}
    for row in run_rows:
        fast_period = _as_optional_int(row.get("fast_period"))
        slow_period = _as_optional_int(row.get("slow_period"))
        leverage = _as_optional_float(row.get("leverage"))
        key = (fast_period, slow_period, leverage)
        group = grouped.setdefault(
            key,
            {
                "fast_period": fast_period,
                "slow_period": slow_period,
                "leverage": leverage,
                "run_count": 0,
                "positive_run_count": 0,
                "oos_positive_run_count": 0,
                "oos_available_count": 0,
                "avg_total_return": 0.0,
                "avg_excess_return": 0.0,
                "avg_oos_total_return": 0.0,
                "avg_oos_excess_return": 0.0,
                "avg_max_drawdown": 0.0,
                "worst_max_drawdown": 0.0,
                "best_total_return": float("-inf"),
                "min_trade_count": None,
                "min_oos_trade_count": None,
                "snapshot_ids": set(),
                "timeframes": set(),
                "run_ids": [],
                "neighbor_count": 0,
                "stable_neighbor_count": 0,
                "neighbor_stability_score": None,
            },
        )
        total_return = float(row.get("total_return", 0.0))
        excess_return = row.get("excess_return")
        oos_total_return = row.get("oos_total_return")
        oos_excess_return = row.get("oos_excess_return")
        oos_trade_count = row.get("oos_trade_count")
        max_drawdown = float(row.get("max_drawdown", 0.0))
        trade_count = int(row.get("trade_count", 0))
        group["run_count"] = int(group["run_count"]) + 1
        if total_return > 0:
            group["positive_run_count"] = int(group["positive_run_count"]) + 1
        if oos_total_return is not None:
            group["oos_available_count"] = int(group["oos_available_count"]) + 1
            if float(oos_total_return) > 0:
                group["oos_positive_run_count"] = int(group["oos_positive_run_count"]) + 1
        group["avg_total_return"] = float(group["avg_total_return"]) + total_return
        group["avg_excess_return"] = float(group["avg_excess_return"]) + (float(excess_return) if excess_return is not None else 0.0)
        group["avg_oos_total_return"] = float(group["avg_oos_total_return"]) + (float(oos_total_return) if oos_total_return is not None else 0.0)
        group["avg_oos_excess_return"] = float(group["avg_oos_excess_return"]) + (float(oos_excess_return) if oos_excess_return is not None else 0.0)
        group["avg_max_drawdown"] = float(group["avg_max_drawdown"]) + max_drawdown
        group["worst_max_drawdown"] = max(float(group["worst_max_drawdown"]), max_drawdown)
        group["best_total_return"] = max(float(group["best_total_return"]), total_return)
        min_trade_count = group["min_trade_count"]
        group["min_trade_count"] = trade_count if min_trade_count is None else min(int(min_trade_count), trade_count)
        min_oos_trade_count = group["min_oos_trade_count"]
        if oos_trade_count is not None:
            group["min_oos_trade_count"] = int(oos_trade_count) if min_oos_trade_count is None else min(int(min_oos_trade_count), int(oos_trade_count))
        cast_snapshot_ids = group["snapshot_ids"]
        cast_timeframes = group["timeframes"]
        cast_run_ids = group["run_ids"]
        if isinstance(cast_snapshot_ids, set):
            cast_snapshot_ids.add(str(row.get("dataset_snapshot_id", "")))
        if isinstance(cast_timeframes, set):
            cast_timeframes.add(str(row.get("timeframe", "")))
        if isinstance(cast_run_ids, list):
            cast_run_ids.append(str(row.get("run_id", "")))

    fast_values = sorted({key[0] for key in grouped if key[0] is not None})
    slow_values = sorted({key[1] for key in grouped if key[1] is not None})
    leverage_values = sorted({key[2] for key in grouped if key[2] is not None})
    fast_index = {value: index for index, value in enumerate(fast_values)}
    slow_index = {value: index for index, value in enumerate(slow_values)}
    leverage_index = {value: index for index, value in enumerate(leverage_values)}

    def averaged_metric(group: dict[str, object], field_name: str) -> float:
        return float(group[field_name]) / int(group["run_count"])

    def oos_positive_ratio_for_group(group: dict[str, object]) -> float | None:
        oos_available_count = int(group["oos_available_count"])
        if oos_available_count == 0:
            return None
        return int(group["oos_positive_run_count"]) / oos_available_count

    def is_stable_group(candidate: dict[str, object]) -> bool:
        if averaged_metric(candidate, "avg_total_return") <= 0 or averaged_metric(candidate, "avg_excess_return") <= 0:
            return False
        if averaged_metric(candidate, "avg_max_drawdown") >= 0.8:
            return False
        if int(candidate["oos_available_count"]) == 0:
            return True
        return (
            averaged_metric(candidate, "avg_oos_total_return") > 0
            and averaged_metric(candidate, "avg_oos_excess_return") > 0
            and float(oos_positive_ratio_for_group(candidate) or 0.0) > 0
        )

    for key, group in grouped.items():
        fast_period, slow_period, leverage = key
        neighbors: list[dict[str, object]] = []
        if fast_period is not None and slow_period is not None:
            current_fast_index = fast_index.get(fast_period)
            current_slow_index = slow_index.get(slow_period)
            if current_fast_index is not None:
                for offset in (-1, 1):
                    next_index = current_fast_index + offset
                    if 0 <= next_index < len(fast_values):
                        neighbor = grouped.get((fast_values[next_index], slow_period, leverage))
                        if neighbor is not None:
                            neighbors.append(neighbor)
            if current_slow_index is not None:
                for offset in (-1, 1):
                    next_index = current_slow_index + offset
                    if 0 <= next_index < len(slow_values):
                        neighbor = grouped.get((fast_period, slow_values[next_index], leverage))
                        if neighbor is not None:
                            neighbors.append(neighbor)
        if leverage is not None:
            current_leverage_index = leverage_index.get(leverage)
            if current_leverage_index is not None:
                for offset in (-1, 1):
                    next_index = current_leverage_index + offset
                    if 0 <= next_index < len(leverage_values):
                        neighbor = grouped.get((fast_period, slow_period, leverage_values[next_index]))
                        if neighbor is not None:
                            neighbors.append(neighbor)
        stable_neighbor_count = sum(1 for neighbor in neighbors if is_stable_group(neighbor))
        group["neighbor_count"] = len(neighbors)
        group["stable_neighbor_count"] = stable_neighbor_count
        group["neighbor_stability_score"] = (
            stable_neighbor_count / len(neighbors)
            if neighbors
            else None
        )

    parameter_groups: list[dict[str, object]] = []
    for group in grouped.values():
        run_count = int(group["run_count"])
        avg_total_return = float(group["avg_total_return"]) / run_count
        avg_excess_return = float(group["avg_excess_return"]) / run_count
        avg_oos_total_return = float(group["avg_oos_total_return"]) / run_count
        avg_oos_excess_return = float(group["avg_oos_excess_return"]) / run_count
        avg_max_drawdown = float(group["avg_max_drawdown"]) / run_count
        worst_max_drawdown = float(group["worst_max_drawdown"])
        return_over_drawdown = avg_total_return / avg_max_drawdown if avg_max_drawdown > 0 else (avg_total_return if avg_total_return > 0 else 0.0)
        positive_ratio = int(group["positive_run_count"]) / run_count
        oos_available_count = int(group["oos_available_count"])
        oos_positive_ratio = int(group["oos_positive_run_count"]) / oos_available_count if oos_available_count else None
        neighbor_stability_score = group["neighbor_stability_score"]
        confidence_components = [
            0.25 * _score_metric(len(group["snapshot_ids"]), 3.0),
            0.25 * float(neighbor_stability_score or 0.0),
            0.2 * positive_ratio,
            0.15 * _score_metric(int(group["min_trade_count"] or 0), 10.0),
            0.15 * (
                _score_metric(avg_oos_total_return, 0.2) * 0.5
                + float(oos_positive_ratio or 0.0) * 0.5
                if oos_available_count
                else 0.0
            ),
        ]
        confidence = round(sum(confidence_components) * 100, 1)
        return_weights = [
            ("avg_total_return", avg_total_return, 0.35, 0.3),
            ("avg_excess_return", avg_excess_return, 0.2, 0.2),
            ("avg_oos_total_return", avg_oos_total_return, 0.25, 0.2),
            ("avg_oos_excess_return", avg_oos_excess_return, 0.1, 0.15),
            ("best_total_return", float(group["best_total_return"]), 0.1, 0.5),
        ]
        weighted_return_score = 0.0
        active_weight_sum = 0.0
        for metric_name, metric_value, weight, target in return_weights:
            if metric_name in {"avg_oos_total_return", "avg_oos_excess_return"}:
                if not oos_available_count:
                    continue
            weighted_return_score += weight * _score_metric(metric_value, target)
            active_weight_sum += weight
        normalized_return_score = (weighted_return_score / active_weight_sum) if active_weight_sum else 0.0
        drawdown_penalty = _clamp_score(avg_max_drawdown / 0.8)
        risk_reward_score = _score_metric(return_over_drawdown, 2.0)
        score = round((0.45 * normalized_return_score + 0.25 * risk_reward_score + 0.3 * (confidence / 100.0)) * (1 - 0.35 * drawdown_penalty) * 100, 1)
        parameter_groups.append(
            {
                "fast_period": group["fast_period"],
                "slow_period": group["slow_period"],
                "leverage": group["leverage"],
                "run_count": run_count,
                "snapshot_count": len(group["snapshot_ids"]),
                "timeframe_count": len(group["timeframes"]),
                "avg_total_return": avg_total_return,
                "avg_excess_return": avg_excess_return,
                "avg_oos_total_return": avg_oos_total_return,
                "avg_oos_excess_return": avg_oos_excess_return,
                "avg_max_drawdown": avg_max_drawdown,
                "worst_max_drawdown": worst_max_drawdown,
                "return_over_drawdown": return_over_drawdown,
                "best_total_return": group["best_total_return"],
                "min_trade_count": group["min_trade_count"],
                "min_oos_trade_count": group["min_oos_trade_count"],
                "positive_ratio": positive_ratio,
                "oos_available_count": oos_available_count,
                "oos_positive_ratio": oos_positive_ratio,
                "neighbor_count": group["neighbor_count"],
                "stable_neighbor_count": group["stable_neighbor_count"],
                "neighbor_stability_score": neighbor_stability_score,
                "score": score,
                "confidence": confidence,
                "run_ids": group["run_ids"],
            }
        )

    robust_rule = BATCH_RECOMMENDATION_RULES["robust_candidate"]
    robust_candidates = [
        {
            **group,
            "reason": (
                "命中稳健候选："
                f"覆盖 {group['snapshot_count']} 个快照，"
                f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"平均样本外收益 {float(group['avg_oos_total_return']) * 100:.2f}%，"
                f"平均样本外超额 {float(group['avg_oos_excess_return']) * 100:.2f}%，"
                f"平均最大回撤 {float(group['avg_max_drawdown']) * 100:.2f}%，"
                f"最少交易数 {int(group['min_trade_count'] or 0)}。"
            ),
        }
        for group in parameter_groups
        if group["snapshot_count"] >= int(robust_rule["min_snapshot_count"])
        and group["positive_ratio"] >= float(robust_rule["min_positive_ratio"])
        and float(group["avg_total_return"]) > 0
        and float(group["avg_excess_return"]) > 0
        and float(group["avg_max_drawdown"]) <= float(robust_rule["max_avg_drawdown"])
        and int(group["min_trade_count"] or 0) >= int(robust_rule["min_trade_count"])
        and int(group["stable_neighbor_count"]) >= int(robust_rule["min_stable_neighbor_count"])
        and float(group["neighbor_stability_score"] or 0.0) >= float(robust_rule["min_neighbor_stability"])
        and (
            int(group["oos_available_count"]) == 0
            or (
                float(group["avg_oos_total_return"]) > 0
                and float(group["avg_oos_excess_return"]) > 0
                and float(group["oos_positive_ratio"] or 0.0) >= float(robust_rule["min_oos_positive_ratio"])
            )
        )
    ]
    robust_keys = {(item["fast_period"], item["slow_period"], item["leverage"]) for item in robust_candidates}
    excluded_keys = {
        (group["fast_period"], group["slow_period"], group["leverage"])
        for group in parameter_groups
        if (
            float(group["avg_total_return"]) <= 0
            or float(group["positive_ratio"]) == 0
            or float(group["worst_max_drawdown"]) >= 0.8
            or (group["oos_available_count"] and float(group["oos_positive_ratio"] or 0.0) == 0)
        )
    }
    high_return_candidates = [
        {
            **group,
            "reason": (
                "命中高收益候选："
                f"最佳收益率 {float(group['best_total_return']) * 100:.2f}%，"
                f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                f"平均最大回撤 {float(group['avg_max_drawdown']) * 100:.2f}%，"
                f"收益回撤比 {float(group['return_over_drawdown']):.2f}，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"样本外收益 {float(group['avg_oos_total_return']) * 100:.2f}%。"
                " 收益上限高，但稳定性还没有达到稳健候选标准。"
            ),
        }
        for group in parameter_groups
        if float(group["best_total_return"]) > 0
        and float(group["avg_total_return"]) > 0
        and (group["fast_period"], group["slow_period"], group["leverage"]) not in robust_keys
        and (group["fast_period"], group["slow_period"], group["leverage"]) not in excluded_keys
    ]
    excluded_combinations = [
        {
            **group,
            "reason": (
                "命中排除规则："
                f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                f"最差最大回撤 {float(group['worst_max_drawdown']) * 100:.2f}%，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"样本外正收益占比 {(float(group['oos_positive_ratio']) * 100):.0f}%"
                if group["oos_positive_ratio"] is not None
                else (
                    "命中排除规则："
                    f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                    f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                    f"最差最大回撤 {float(group['worst_max_drawdown']) * 100:.2f}%，"
                    f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                    f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                    "当前没有样本外正收益记录。"
                )
            ),
        }
        for group in parameter_groups
        if (
            float(group["avg_total_return"]) <= 0
            or float(group["positive_ratio"]) == 0
            or float(group["worst_max_drawdown"]) >= 0.8
            or (group["oos_available_count"] and float(group["oos_positive_ratio"] or 0.0) == 0)
        )
    ]

    parameter_groups.sort(key=lambda item: (float(item["score"]), float(item["confidence"]), float(item["avg_oos_excess_return"]), float(item["avg_excess_return"])), reverse=True)
    robust_candidates.sort(key=lambda item: (float(item["confidence"]), float(item["score"]), float(item["avg_oos_excess_return"])), reverse=True)
    high_return_candidates.sort(key=lambda item: (float(item["score"]), float(item["best_total_return"]), float(item["confidence"])), reverse=True)
    excluded_combinations.sort(key=lambda item: (float(item["score"]), float(item["confidence"])))

    return (
        parameter_groups,
        {
            "robust_candidates": robust_candidates[:5],
            "high_return_candidates": high_return_candidates[:5],
            "excluded_combinations": excluded_combinations[:5],
        },
        _build_batch_scoring_rules(),
    )


def _as_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)
