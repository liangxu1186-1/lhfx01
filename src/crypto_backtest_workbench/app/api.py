"""Minimal HTTP API for the React workbench."""

from __future__ import annotations

import json
import mimetypes
import contextlib
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from crypto_backtest_workbench.app.batch_scoring import build_batch_recommendations
from crypto_backtest_workbench.app.paper_trading import (
    CreatePaperSessionRequest,
    FilePaperTradingRepository,
    TickPaperSessionRequest,
    create_paper_session_workflow,
    tick_paper_session_workflow,
)
from crypto_backtest_workbench.app.paper_trading.live_klines import (
    FileLiveKlineCache,
    LiveKlineStreamSpec,
    stream_binance_usdm_klines,
)
from crypto_backtest_workbench.app.paper_trading.market_data import PaperLocalKlineMarketDataClient, PaperMarketDataClient
from crypto_backtest_workbench.app.paper_trading.models import PaperSession
from crypto_backtest_workbench.app.paper_trading.signal_snapshot import build_paper_signal_snapshot
from crypto_backtest_workbench.app.readmodels.parameters import ParameterLabRow, build_parameter_lab_rows
from crypto_backtest_workbench.app.readmodels import (
    build_parameter_research_workspace,
    build_workspace_datasets,
    build_workspace_overview,
    build_workspace_overview_equity,
    build_workspace_parameter_lab,
    build_research_workflow,
    build_stable_pool_trade_attribution,
    build_workspace_run_detail,
    build_workspace_run_index,
    build_workspace_snapshot,
    build_workspace_source,
    json_ready,
    load_parameter_group_detail,
    load_research_candidate_trade_attribution,
)
from crypto_backtest_workbench.app.workflows import (
    ParameterExperimentBatchRequest,
    ParameterExperimentTaskRequest,
    build_parameter_experiment_batch,
    build_parameter_experiment_task,
    ExecutionVerificationRequest,
    RunBacktestWorkflowRequest,
    ingest_dataset_workflow,
    run_execution_verification_workflow,
    run_parameter_experiment_batch_workflow,
    run_parameter_experiment_task_workflow,
    run_backtest_task_workflow,
)
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    ExperimentBatch,
    MarketType,
    ParameterExperiment,
    PriceType,
    ResearchNote,
    SearchType,
    SeedPolicy,
    TaskStatus,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.data.fetchers import build_default_history_fetcher
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.jobs.task_models import TaskRecord
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
RISK_PCT_OF_EQUITY_POLICY_REF = "risk_pct_of_equity"
RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF = "risk_pct_of_cash_allocation"
RESEARCH_NOTE_DECISION_STATUSES = frozenset({"candidate", "observing", "approved", "rejected", "archived"})
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError)


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
        self.readmodel_cache: dict[str, tuple[tuple[int, int], object]] = {}
        self.readmodel_cache_lock = threading.Lock()
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
            if path == "/api/paper-sessions":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        paper_sessions=self._build_paper_session_index(),
                    ),
                )
                return
            if path.startswith("/api/paper-sessions/") and path.endswith("/signal-snapshot"):
                session_id = unquote(path.removeprefix("/api/paper-sessions/").removesuffix("/signal-snapshot"))
                allow_backfill = query.get("backfill", ["0"])[0] in {"1", "true", "yes"}
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        paper_signal_snapshot=self._build_paper_signal_snapshot(session_id, allow_backfill=allow_backfill),
                    ),
                )
                return
            if path.startswith("/api/paper-sessions/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        paper_session=self._build_paper_session_detail(
                            unquote(path.removeprefix("/api/paper-sessions/"))
                        ),
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
                        parameter_lab=self._build_cached_parameter_lab(),
                    ),
                )
                return
            if path == "/api/parameter-research":
                research_workspace = self._build_research_workspace()
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        research_subjects=research_workspace["subjects"],
                        parameter_groups=self._filter_parameter_groups(
                            research_workspace["parameter_groups"],
                            query,
                        ),
                    ),
                )
                return
            if path == "/api/research-workflow":
                research_workflow = build_research_workflow(
                    FileRunRepository(self.server.data_dir),
                    FileResearchNoteRepository(self.server.data_dir),
                    data_dir=self.server.data_dir,
                )
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        research_workflow=research_workflow.as_dict(),
                    ),
                )
                return
            if path.startswith("/api/research-candidates/") and path.endswith("/filter-results"):
                candidate_id = unquote(path.removeprefix("/api/research-candidates/").removesuffix("/filter-results"))
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        filter_results=self._build_research_candidate_filter_results(candidate_id),
                    ),
                )
                return
            if path.startswith("/api/research-candidates/") and path.endswith("/trade-attribution"):
                candidate_id = unquote(path.removeprefix("/api/research-candidates/").removesuffix("/trade-attribution"))
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        trade_attribution=load_research_candidate_trade_attribution(
                            FileRunRepository(self.server.data_dir),
                            candidate_id=candidate_id,
                            data_dir=self.server.data_dir,
                        ).as_dict(),
                    ),
                )
                return
            if path == "/api/stable-pool/trade-attribution":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        stable_pool_trade_attribution=build_stable_pool_trade_attribution(
                            FileRunRepository(self.server.data_dir),
                            FileResearchNoteRepository(self.server.data_dir),
                        ),
                    ),
                )
                return
            if path == "/api/research-subjects":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        research_subjects=self._build_research_workspace()["subjects"],
                    ),
                )
                return
            if path == "/api/parameter-groups":
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_groups=self._filter_parameter_groups(
                            self._build_research_workspace()["parameter_groups"],
                            query,
                        ),
                    ),
                )
                return
            if path.startswith("/api/parameter-groups/"):
                self._send_json(
                    HTTPStatus.OK,
                    self._build_workspace_payload(
                        parameter_group=self._build_parameter_group_detail(
                            unquote(path.removeprefix("/api/parameter-groups/"))
                        ),
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
        except CLIENT_DISCONNECT_ERRORS:
            return
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
            if path == "/api/runs":
                status, body = self._handle_run(payload)
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
            if path == "/api/paper-sessions":
                status, body = self._handle_create_paper_session(payload)
                self._send_json(status, body)
                return
            if path.startswith("/api/paper-sessions/") and path.endswith("/tick"):
                session_id = unquote(path.removeprefix("/api/paper-sessions/").removesuffix("/tick"))
                status, body = self._handle_tick_paper_session(session_id, payload)
                self._send_json(status, body)
                return
            if path == "/api/research-pool":
                status, body = self._handle_add_to_research_pool(payload)
                self._send_json(status, body)
                return
            if path == "/api/stable-pool":
                status, body = self._handle_add_to_stable_pool(payload)
                self._send_json(status, body)
                return
            if path.startswith("/api/stable-candidates/") and path.endswith("/execution-verification"):
                candidate_id = unquote(path.removeprefix("/api/stable-candidates/").removesuffix("/execution-verification"))
                status, body = self._handle_run_stable_candidate_execution_verification(candidate_id, payload)
                self._send_json(status, body)
                return
            if path.startswith("/api/stable-candidates/") and path.endswith("/execution-filter-experiments"):
                candidate_id = unquote(path.removeprefix("/api/stable-candidates/").removesuffix("/execution-filter-experiments"))
                status, body = self._handle_run_stable_candidate_execution_filter_experiment(candidate_id, payload)
                self._send_json(status, body)
                return
            if path.startswith("/api/research-candidates/") and path.endswith("/risk-matrix"):
                candidate_id = unquote(path.removeprefix("/api/research-candidates/").removesuffix("/risk-matrix"))
                status, body = self._handle_run_research_candidate_risk_matrix(candidate_id, payload)
                self._send_json(status, body)
                return
            if path.startswith("/api/research-candidates/") and path.endswith("/filter-experiments"):
                candidate_id = unquote(path.removeprefix("/api/research-candidates/").removesuffix("/filter-experiments"))
                status, body = self._handle_run_research_candidate_filter_experiment(candidate_id, payload)
                self._send_json(status, body)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Unknown endpoint: {path}"}})
        except CLIENT_DISCONNECT_ERRORS:
            return
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
            if path.startswith("/api/research-notes/"):
                note_id = unquote(path.removeprefix("/api/research-notes/"))
                self._send_json(HTTPStatus.OK, self._handle_delete_research_note(note_id))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Unknown endpoint: {path}"}})
        except CLIENT_DISCONNECT_ERRORS:
            return
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
        mapped = dict(payload)
        mapped["strategy_name"] = "ema_crossover"
        return self._handle_run(mapped)

    def _handle_run(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        snapshot = _load_snapshot(self.server.data_dir, _require_str(payload, "snapshot_id"))
        validation_split = _build_validation_split(
            payload=payload,
            snapshot=snapshot,
        )
        qty_policy_ref, constraints = _build_execution_constraints(payload)
        strategy_name = str(payload.get("strategy_name", "ema_crossover"))

        request = RunBacktestWorkflowRequest(
            run_id=_require_str(payload, "run_id"),
            snapshot=snapshot,
            strategy_params=_build_strategy_params_from_payload(payload, strategy_name=strategy_name, qty_policy_ref=qty_policy_ref),
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
        try:
            return json_ready(task_repository.load_task(task_id))
        except (FileNotFoundError, json.JSONDecodeError):
            now = datetime.now(UTC)
            return json_ready(
                TaskRecord(
                    task_id=task_id,
                    task_kind="background",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                    failure_code=None,
                    failure_message=None,
                    failure_stage=None,
                )
            )

    def _build_paper_session_index(self) -> list[dict[str, object]]:
        repository = FilePaperTradingRepository(self.server.data_dir)
        sessions = repository.list_sessions()
        for session in sessions:
            self._ensure_paper_kline_streams(session)
        return [self._paper_session_payload(session) for session in sessions]

    def _build_paper_session_detail(self, session_id: str) -> dict[str, object]:
        repository = FilePaperTradingRepository(self.server.data_dir)
        session = repository.load_session(session_id)
        self._ensure_paper_kline_streams(session)
        return self._paper_session_payload(session, include_records=True)

    def _build_paper_signal_snapshot(self, session_id: str, *, allow_backfill: bool = False) -> dict[str, object]:
        repository = FilePaperTradingRepository(self.server.data_dir)
        session = repository.load_session(session_id)
        self._ensure_paper_kline_streams(session)
        return build_paper_signal_snapshot(
            session=session,
            data_dir=self.server.data_dir,
            allow_backfill=allow_backfill,
        )

    def _handle_create_paper_session(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        repository = FilePaperTradingRepository(self.server.data_dir)
        session = create_paper_session_workflow(
            paper_repository=repository,
            run_repository=FileRunRepository(self.server.data_dir),
            request=CreatePaperSessionRequest(
                session_id=_optional_str(payload.get("session_id")),
                stable_candidate_id=_require_str(payload, "stable_candidate_id"),
                source_run_id=_require_str(payload, "source_run_id"),
                initial_cash=_optional_number(payload.get("initial_cash")),
                exchange=_optional_str(payload.get("exchange")),
                symbol=_optional_str(payload.get("symbol")),
                market_type=_optional_str(payload.get("market_type")),
                price_type=_optional_str(payload.get("price_type")),
                strategy_timeframe=_optional_str(payload.get("strategy_timeframe")),
                execution_timeframe=str(payload.get("execution_timeframe", "5m")),
            ),
        )
        self._ensure_paper_kline_streams(session)
        return HTTPStatus.CREATED, {"paper_session": self._paper_session_payload(session)}

    def _handle_tick_paper_session(self, session_id: str, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        repository = FilePaperTradingRepository(self.server.data_dir)
        session = repository.load_session(session_id)
        self._ensure_paper_kline_streams(session)
        exchange_options = _optional_dict(payload.get("exchange_options")) or {}
        allow_rest_fallback = bool(payload.get("allow_rest_fallback", False))
        rest_client = None
        if allow_rest_fallback:
            fetcher = build_default_history_fetcher(str(payload.get("exchange") or session.exchange), options=exchange_options)
            rest_client = PaperMarketDataClient(fetcher)
        result = tick_paper_session_workflow(
            paper_repository=repository,
            feature_repository=FileFeatureRepository(self.server.data_dir),
            market_data_client=PaperLocalKlineMarketDataClient(
                data_dir=self.server.data_dir,
                live_cache=FileLiveKlineCache(self.server.data_dir),
                rest_client=rest_client,
                allow_rest_fallback=allow_rest_fallback,
            ),
            request=TickPaperSessionRequest(
                session_id=session_id,
                until=_parse_optional_datetime(payload.get("until")),
            ),
        )
        return (
            HTTPStatus.OK,
            {
                "paper_session": self._paper_session_payload(result.session),
                "strategy_bar_count": result.strategy_bar_count,
                "execution_bar_count": result.execution_bar_count,
                "new_signal_count": result.new_signal_count,
                "order_count": result.order_count,
                "fill_count": result.fill_count,
                "closed_trade_count": result.closed_trade_count,
                "warning_count": result.warning_count,
                "orders": json_ready(result.orders),
                "fills": json_ready(result.fills),
                "trades": json_ready(result.trades),
                "warnings": json_ready(result.warnings),
            },
        )

    def _paper_session_payload(self, session: PaperSession, *, include_records: bool = False) -> dict[str, object]:
        payload = json_ready(session)
        payload["live_streams"] = [
            FileLiveKlineCache(self.server.data_dir).load_status(spec)
            for spec in self._paper_kline_specs(session)
        ]
        if include_records:
            repository = FilePaperTradingRepository(self.server.data_dir)
            payload["orders"] = repository.load_orders(session.session_id)
            payload["fills"] = repository.load_fills(session.session_id)
            payload["trades"] = repository.load_trades(session.session_id)
            payload["warnings"] = repository.load_warnings(session.session_id)
        return payload

    def _ensure_paper_kline_streams(self, session: PaperSession) -> None:
        if session.status != "active" or _exchange_alias(session.exchange) != "binanceusdm":
            return
        specs = self._paper_kline_specs(session)
        for spec in specs:
            key = f"paper-kline:{_exchange_alias(spec.exchange)}:{spec.symbol}:{spec.timeframe}:{spec.price_type.value}"
            existing = self.server.background_threads.get(key)
            if existing is not None and existing.is_alive():
                continue
            worker = threading.Thread(
                target=_run_binance_kline_stream,
                args=(self.server.data_dir, spec),
                name=key,
                daemon=True,
            )
            self.server.background_threads[key] = worker
            worker.start()

    def _paper_kline_specs(self, session: PaperSession) -> list[LiveKlineStreamSpec]:
        timeframes = []
        for timeframe in (session.strategy_timeframe, session.execution_timeframe):
            if timeframe and timeframe not in timeframes:
                timeframes.append(timeframe)
        return [
            LiveKlineStreamSpec(
                exchange=_exchange_alias(session.exchange),
                symbol=session.symbol,
                market_type=MarketType(session.market_type),
                timeframe=timeframe,
                price_type=PriceType(session.price_type),
            )
            for timeframe in timeframes
        ]

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
        run_repository = FileRunRepository(self.server.data_dir)
        run_rows = [
            row.as_dict()
            for row in build_parameter_lab_rows(
                run_repository,
                run_ids=sorted(run_ids),
                include_execution_filter_experiments=True,
            )
        ]
        parameter_groups, recommendations, scoring_rules = build_batch_recommendations(
            run_rows,
            strategy_name=batch.strategy_name,
        )
        return {
            "batch": json_ready(batch),
            "execution": execution,
            "experiments": experiments,
            "run_rows": run_rows,
            "parameter_groups": parameter_groups,
            "recommendations": recommendations,
            "scoring_rules": scoring_rules,
        }

    def _build_research_workspace(self) -> dict[str, object]:
        cached = self._cached_readmodel("parameter_research")
        if cached is not None:
            return cached  # type: ignore[return-value]
        run_repository = FileRunRepository(self.server.data_dir)
        workspace = build_parameter_research_workspace(
            run_repository,
            data_dir=self.server.data_dir,
        ).as_dict()
        self._store_cached_readmodel("parameter_research", workspace)
        return workspace

    def _build_cached_parameter_lab(self) -> dict[str, object]:
        cached = self._cached_readmodel("parameter_lab")
        if cached is not None:
            return cached  # type: ignore[return-value]
        parameter_lab = build_workspace_parameter_lab(data_dir=self.server.data_dir)
        self._store_cached_readmodel("parameter_lab", parameter_lab)
        return parameter_lab

    def _build_parameter_group_detail(self, group_key: str) -> dict[str, object]:
        run_repository = FileRunRepository(self.server.data_dir)
        return load_parameter_group_detail(
            run_repository,
            group_key=group_key,
            data_dir=self.server.data_dir,
        ).as_dict()

    def _cached_readmodel(self, key: str) -> object | None:
        signature = _readmodel_signature(self.server.data_dir)
        with self.server.readmodel_cache_lock:
            cached = self.server.readmodel_cache.get(key)
            if cached and cached[0] == signature:
                return cached[1]
        return None

    def _store_cached_readmodel(self, key: str, value: object) -> None:
        signature = _readmodel_signature(self.server.data_dir)
        with self.server.readmodel_cache_lock:
            self.server.readmodel_cache[key] = (signature, value)

    def _filter_parameter_groups(
        self,
        parameter_groups: list[dict[str, object]],
        query: dict[str, list[str]],
    ) -> list[dict[str, object]]:
        filters = {
            "strategy_name": _first_query_value(query, "strategy_name"),
            "symbol": _first_query_value(query, "symbol"),
            "timeframe": _first_query_value(query, "timeframe"),
            "validation_split_id": _first_query_value(query, "validation_split_id"),
            "qty_policy_ref": _first_query_value(query, "qty_policy_ref"),
            "leverage": _first_query_value(query, "leverage"),
            "subject_key": _first_query_value(query, "subject_key"),
        }
        filtered: list[dict[str, object]] = []
        for group in parameter_groups:
            if filters["subject_key"] and group.get("subject_key") != filters["subject_key"]:
                continue
            if filters["strategy_name"] and group.get("strategy_name") != filters["strategy_name"]:
                continue
            if filters["symbol"] and group.get("symbol") != filters["symbol"]:
                continue
            if filters["timeframe"] and group.get("timeframe") != filters["timeframe"]:
                continue
            if filters["validation_split_id"] and group.get("validation_split_id") != filters["validation_split_id"]:
                continue
            if filters["qty_policy_ref"] and group.get("qty_policy_ref") != filters["qty_policy_ref"]:
                continue
            if filters["leverage"] and str(group.get("leverage")) != filters["leverage"]:
                continue
            filtered.append(group)
        return filtered

    def _build_research_note_index(self, query: dict[str, list[str]]) -> list[dict[str, object]]:
        repository = FileResearchNoteRepository(self.server.data_dir)
        target_type = _first_query_value(query, "target_type")
        target_id = _first_query_value(query, "target_id")
        decision_status = _optional_query_decision_status(query, "decision_status")
        label = _first_query_value(query, "label")
        linked_batch_id = _first_query_value(query, "linked_batch_id")
        linked_parameter_group = _first_query_value(query, "linked_parameter_group")
        return [
            json_ready(note)
            for note in repository.list_notes(
                target_type=target_type,
                target_id=target_id,
                decision_status=decision_status,
                label=label,
                linked_batch_id=linked_batch_id,
                linked_parameter_group=linked_parameter_group,
            )
        ]

    def _handle_parameter_experiment(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        snapshot = _load_snapshot(self.server.data_dir, _require_str(payload, "snapshot_id"))
        experiment_id = _require_str(payload, "experiment_id")
        qty_policy_ref = _resolve_qty_policy_ref(payload)
        strategy_name = str(payload.get("strategy_name", "ema_crossover"))
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        if experiment_id in experiment_repository.list_experiment_ids():
            raise FileExistsError(f"Parameter experiment already exists: {experiment_id}")
        request = ParameterExperimentTaskRequest(
            experiment_id=experiment_id,
            snapshot=snapshot,
            search_type=SearchType(str(payload.get("search_type", SearchType.GRID.value))),
            strategy_name=strategy_name,
            strategy_version=str(payload.get("strategy_version", "v2" if strategy_name == "ema_pullback_atr_v2" else "v1")),
            fast_periods=_optional_int_tuple(payload, "fast_periods"),
            slow_periods=_optional_int_tuple(payload, "slow_periods"),
            trend_fast_periods=_optional_int_tuple(payload, "trend_fast_periods"),
            trend_slow_periods=_optional_int_tuple(payload, "trend_slow_periods"),
            atr_entry_tolerances=_optional_float_tuple(payload, "atr_entry_tolerances"),
            atr_stop_mults=_optional_float_tuple(payload, "atr_stop_mults"),
            risk_reward_ratios=_optional_float_tuple(payload, "risk_reward_ratios"),
            entry_ema_period=int(payload.get("entry_ema_period", 21)),
            atr_period=int(payload.get("atr_period", 14)),
            min_atr_pct_of_price=float(payload.get("min_atr_pct_of_price", 0.002)),
            min_stop_pct=float(payload.get("min_stop_pct", 0.003)),
            qty_policy_ref=qty_policy_ref,
            qty=_optional_number(payload.get("qty")),
            cash_allocation_pct=_optional_number(
                payload.get("cash_allocation_pct"),
                default=(
                    DEFAULT_CASH_ALLOCATION_PCT
                    if qty_policy_ref in {DEFAULT_QTY_POLICY_REF, RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF}
                    else None
                ),
            ),
            risk_pct_per_trade=_optional_number(payload.get("risk_pct_per_trade")),
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=_require_float_tuple(payload, "leverage_candidates", fallback_field_name="leverage"),
            fee_rate=float(payload.get("fee_rate", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            min_notional=float(payload.get("min_notional", 0.0)),
            execution_protection_sets=_optional_dict_tuple(payload, "execution_protection_sets"),
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
        strategy_name = str(payload.get("strategy_name", "ema_crossover"))
        request = ParameterExperimentBatchRequest(
            batch_id=batch_id,
            snapshots=snapshots,
            search_type=SearchType(str(payload.get("search_type", SearchType.GRID.value))),
            strategy_name=strategy_name,
            strategy_version=str(payload.get("strategy_version", "v2" if strategy_name == "ema_pullback_atr_v2" else "v1")),
            fast_periods=_optional_int_tuple(payload, "fast_periods"),
            slow_periods=_optional_int_tuple(payload, "slow_periods"),
            trend_fast_periods=_optional_int_tuple(payload, "trend_fast_periods"),
            trend_slow_periods=_optional_int_tuple(payload, "trend_slow_periods"),
            atr_entry_tolerances=_optional_float_tuple(payload, "atr_entry_tolerances"),
            atr_stop_mults=_optional_float_tuple(payload, "atr_stop_mults"),
            risk_reward_ratios=_optional_float_tuple(payload, "risk_reward_ratios"),
            entry_ema_period=int(payload.get("entry_ema_period", 21)),
            atr_period=int(payload.get("atr_period", 14)),
            min_atr_pct_of_price=float(payload.get("min_atr_pct_of_price", 0.002)),
            min_stop_pct=float(payload.get("min_stop_pct", 0.003)),
            qty_policy_ref=qty_policy_ref,
            qty=_optional_number(payload.get("qty")),
            cash_allocation_pct=_optional_number(
                payload.get("cash_allocation_pct"),
                default=(
                    DEFAULT_CASH_ALLOCATION_PCT
                    if qty_policy_ref in {DEFAULT_QTY_POLICY_REF, RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF}
                    else None
                ),
            ),
            risk_pct_per_trade=_optional_number(payload.get("risk_pct_per_trade")),
            cash_allocation_pct_candidates=_optional_float_tuple(payload, "cash_allocation_pct_candidates"),
            risk_pct_per_trade_candidates=_optional_float_tuple(payload, "risk_pct_per_trade_candidates"),
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=_require_float_tuple(payload, "leverage_candidates", fallback_field_name="leverage"),
            fee_rate=float(payload.get("fee_rate", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 0.0)),
            min_notional=float(payload.get("min_notional", 0.0)),
            execution_protection_sets=_optional_dict_tuple(payload, "execution_protection_sets"),
            benchmark_enabled=str(payload.get("benchmark", "buy_and_hold")) == "buy_and_hold",
            max_samples=int(payload["max_samples"]) if payload.get("max_samples") is not None else None,
            seed=int(payload["seed"]) if payload.get("seed") is not None else None,
            validation_split_factory=_build_batch_validation_split_factory(payload=payload, batch_id=batch_id),
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

    def _submit_parameter_experiment_batch_request(self, request: ParameterExperimentBatchRequest) -> tuple[HTTPStatus, dict[str, object]]:
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        if request.batch_id in batch_repository.list_batch_ids():
            raise FileExistsError(f"Parameter experiment batch already exists: {request.batch_id}")
        task, batch, child_requests, planned_run_count = build_parameter_experiment_batch(request)
        task_repository = FileTaskRepository(self.server.data_dir)
        task_repository.save_task(task)
        batch_repository.save_batch(batch)
        batch_repository.save_execution_index(
            request.batch_id,
            {
                "batch_id": request.batch_id,
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
            name=f"parameter-experiment-batch:{request.batch_id}",
        )
        self.server.background_threads[task.task_id] = worker
        worker.start()
        return (
            HTTPStatus.ACCEPTED,
            {
                "task_id": task.task_id,
                "task_status": task.status.value,
                "batch_id": request.batch_id,
                "search_type": request.search_type.value,
                "planned_experiment_count": len(child_requests),
                "planned_run_count": planned_run_count,
            },
        )

    def _handle_run_research_candidate_risk_matrix(self, candidate_id: str, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("candidate_id must not be empty")
        run_repository = FileRunRepository(self.server.data_dir)
        group_detail = load_parameter_group_detail(run_repository, group_key=candidate_id, data_dir=self.server.data_dir)
        group = group_detail.group
        if group.strategy_name != "ema_pullback_atr_v2":
            raise ValueError("Risk matrix currently supports EMA Pullback ATR v2 candidates")
        snapshots = tuple(_load_snapshot(self.server.data_dir, run.dataset_snapshot_id) for run in group_detail.runs)
        if not snapshots:
            raise ValueError("Candidate has no evidence runs to derive snapshots")
        representative_run = group_detail.runs[0]
        representative_rows = build_parameter_lab_rows(run_repository, run_ids=[representative_run.run_id])
        if not representative_rows:
            raise ValueError("Representative run parameters are not available")
        representative_parameter_row = representative_rows[0]
        qty_policy_ref = str(group.qty_policy_ref or RISK_PCT_OF_EQUITY_POLICY_REF)
        risk_candidates = _optional_float_tuple(payload, "risk_pct_per_trade_candidates") or (0.01, 0.03, 0.05, 0.10)
        cash_candidates = _optional_float_tuple(payload, "cash_allocation_pct_candidates")
        if qty_policy_ref == DEFAULT_QTY_POLICY_REF:
            cash_candidates = cash_candidates or (30.0, 50.0, 95.0)
            risk_candidates = ()
        if qty_policy_ref == RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF and not cash_candidates:
            cash_candidates = (30.0, 50.0, 95.0)
        leverage_candidates = _optional_float_tuple(payload, "leverage_candidates") or (1.0, 3.0, 5.0, 10.0)
        batch_id = str(payload.get("batch_id") or f"risk-matrix-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}")
        request = ParameterExperimentBatchRequest(
            batch_id=batch_id,
            snapshots=snapshots,
            search_type=SearchType.GRID,
            strategy_name=group.strategy_name,
            strategy_version="v2",
            trend_fast_periods=(int(group.trend_fast_period),),
            trend_slow_periods=(int(group.trend_slow_period),),
            atr_entry_tolerances=(float(group.atr_entry_tolerance or 0.0),),
            atr_stop_mults=(float(group.atr_stop_mult or 1.5),),
            risk_reward_ratios=(float(group.risk_reward_ratio or 1.5),),
            entry_ema_period=int(group.entry_ema_period or 21),
            atr_period=int(group.atr_period or 14),
            min_atr_pct_of_price=float(payload.get("min_atr_pct_of_price", 0.002)),
            min_stop_pct=float(payload.get("min_stop_pct", 0.003)),
            qty_policy_ref=qty_policy_ref,
            qty=None,
            cash_allocation_pct=float(group.cash_allocation_pct) if group.cash_allocation_pct is not None and qty_policy_ref == DEFAULT_QTY_POLICY_REF else None,
            cash_allocation_pct_candidates=cash_candidates,
            risk_pct_per_trade=float(group.risk_pct_per_trade) if group.risk_pct_per_trade is not None and not risk_candidates else None,
            risk_pct_per_trade_candidates=risk_candidates,
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=leverage_candidates,
            fee_rate=float(representative_parameter_row.fee_rate or 0.0),
            slippage_bps=float(representative_parameter_row.slippage_bps or 0.0),
            min_notional=float(payload.get("min_notional", 0.0)),
            benchmark_enabled=True,
            validation_split_factory=_build_batch_validation_split_factory(
                payload={
                    "validation_split_mode": "auto_ratio",
                    "oos_ratio": float(payload.get("oos_ratio", 0.3)),
                    "warmup_bars": int(payload.get("warmup_bars", 0)),
                },
                batch_id=batch_id,
            ),
        )
        return self._submit_parameter_experiment_batch_request(request)

    def _handle_run_research_candidate_filter_experiment(self, candidate_id: str, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("candidate_id must not be empty")
        run_repository = FileRunRepository(self.server.data_dir)
        group_detail = load_parameter_group_detail(run_repository, group_key=candidate_id, data_dir=self.server.data_dir)
        group = group_detail.group
        if group.strategy_name != "ema_pullback_atr_v2":
            raise ValueError("Filter experiments currently support EMA Pullback ATR v2 candidates")
        snapshots = tuple(_load_snapshot(self.server.data_dir, run.dataset_snapshot_id) for run in group_detail.runs)
        if not snapshots:
            raise ValueError("Candidate has no evidence runs to derive snapshots")
        representative_run = group_detail.runs[0]
        representative_rows = build_parameter_lab_rows(run_repository, run_ids=[representative_run.run_id])
        if not representative_rows:
            raise ValueError("Representative run parameters are not available")
        representative_parameter_row = representative_rows[0]
        qty_policy_ref = str(group.qty_policy_ref or RISK_PCT_OF_EQUITY_POLICY_REF)
        signal_filter_sets = _build_signal_filter_sets(payload)
        batch_id = str(payload.get("batch_id") or f"filter-experiment-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}")
        request = ParameterExperimentBatchRequest(
            batch_id=batch_id,
            snapshots=snapshots,
            search_type=SearchType.GRID,
            strategy_name=group.strategy_name,
            strategy_version="v2",
            trend_fast_periods=(int(group.trend_fast_period),),
            trend_slow_periods=(int(group.trend_slow_period),),
            atr_entry_tolerances=(float(group.atr_entry_tolerance or 0.0),),
            atr_stop_mults=(float(group.atr_stop_mult or 1.5),),
            risk_reward_ratios=(float(group.risk_reward_ratio or 1.5),),
            entry_ema_period=int(group.entry_ema_period or 21),
            atr_period=int(group.atr_period or 14),
            min_atr_pct_of_price=float(payload.get("min_atr_pct_of_price", 0.002)),
            min_stop_pct=float(payload.get("min_stop_pct", 0.003)),
            qty_policy_ref=qty_policy_ref,
            qty=None,
            cash_allocation_pct=float(group.cash_allocation_pct) if group.cash_allocation_pct is not None else None,
            risk_pct_per_trade=float(group.risk_pct_per_trade) if group.risk_pct_per_trade is not None else None,
            initial_cash=float(payload.get("initial_cash", 10_000.0)),
            leverage_candidates=(float(group.leverage or representative_parameter_row.leverage or 1.0),),
            fee_rate=float(representative_parameter_row.fee_rate or 0.0),
            slippage_bps=float(representative_parameter_row.slippage_bps or 0.0),
            min_notional=float(payload.get("min_notional", 0.0)),
            signal_filter_sets=signal_filter_sets,
            benchmark_enabled=True,
            validation_split_factory=_build_batch_validation_split_factory(
                payload={
                    "validation_split_mode": "auto_ratio",
                    "oos_ratio": float(payload.get("oos_ratio", 0.3)),
                    "warmup_bars": int(payload.get("warmup_bars", 0)),
                },
                batch_id=batch_id,
            ),
        )
        status, body = self._submit_parameter_experiment_batch_request(request)
        body["filter_set_count"] = len(signal_filter_sets)
        body["filter_sets"] = list(signal_filter_sets)
        return status, body

    def _build_research_candidate_filter_results(self, candidate_id: str) -> dict[str, object]:
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("candidate_id must not be empty")
        run_repository = FileRunRepository(self.server.data_dir)
        group_detail = load_parameter_group_detail(run_repository, group_key=candidate_id, data_dir=self.server.data_dir)
        base_group = group_detail.group
        rows = build_parameter_lab_rows(run_repository)
        filtered_rows = [
            row
            for row in rows
            if row.signal_filter_summary and _matches_filter_result_signature(base_group, row)
        ]
        rows_by_filter: dict[str, list[ParameterLabRow]] = {}
        for row in filtered_rows:
            rows_by_filter.setdefault(str(row.signal_filter_summary), []).append(row)
        filter_groups = [
            _build_filter_result_group(filter_summary, filter_rows, base_group=base_group)
            for filter_summary, filter_rows in rows_by_filter.items()
        ]
        filter_groups.sort(
            key=lambda item: (
                float(item.get("avg_oos_delta") or -10_000),
                -float(item.get("avg_max_drawdown") or 10_000),
                str(item.get("filter_summary") or ""),
            ),
            reverse=True,
        )
        return {
            "candidate_id": candidate_id,
            "base_group": base_group.as_dict(),
            "base_runs": [run.as_dict() for run in group_detail.runs],
            "filter_groups": filter_groups,
            "filter_runs": [row.as_dict() for row in filtered_rows],
        }

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
        decision_status = _normalize_decision_status(payload.get("decision_status"))
        decision_reason = _optional_str(payload.get("decision_reason"))
        linked_batch_id = _optional_str(payload.get("linked_batch_id"))
        linked_parameter_group = _optional_str(payload.get("linked_parameter_group"))
        confidence_score = _optional_float(payload.get("confidence_score"))
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
            decision_status=decision_status,
            decision_reason=decision_reason,
            confidence_score=confidence_score,
            linked_batch_id=linked_batch_id,
            linked_parameter_group=linked_parameter_group,
        )
        repository.save_note(note)
        return (
            HTTPStatus.CREATED,
            {
                "note": json_ready(note),
            },
        )

    def _handle_delete_research_note(self, note_id: str) -> dict[str, object]:
        if not note_id:
            raise ValueError("note_id must not be empty")
        repository = FileResearchNoteRepository(self.server.data_dir)
        note = repository.load_note(note_id)
        repository.delete_note(note_id)
        return {
            "deleted_note_id": note_id,
            "target_type": note.target_type,
            "target_id": note.target_id,
        }

    def _handle_add_to_research_pool(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        source_run_id = _require_str(payload, "source_run_id")
        run_repository = FileRunRepository(self.server.data_dir)
        _ = run_repository.load_run(source_run_id)
        rows_by_run_id = {row.run_id: row for row in build_parameter_lab_rows(run_repository)}
        source_row = rows_by_run_id.get(source_run_id)
        if source_row is None:
            raise FileNotFoundError(f"Run not found in parameter lab: {source_run_id}")
        group_key = self._parameter_group_key_for_run(source_run_id)
        note_payload = {
            "target_type": "research_candidate",
            "target_id": group_key,
            "content": str(payload.get("note") or "加入研究池").strip() or "加入研究池",
            "labels": ["research_pool"],
            "decision_status": "candidate",
            "linked_parameter_group": group_key,
        }
        status, body = self._handle_create_research_note(note_payload)
        return status, {"research_candidate_id": group_key, "source_run_id": source_run_id, **body}

    def _handle_add_to_stable_pool(self, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        candidate_id = _require_str(payload, "research_candidate_id")
        chosen_run_id = _optional_str(payload.get("chosen_run_id"))
        _ = load_parameter_group_detail(
            FileRunRepository(self.server.data_dir),
            group_key=candidate_id,
            data_dir=self.server.data_dir,
        )
        if chosen_run_id:
            _ = FileRunRepository(self.server.data_dir).load_run(chosen_run_id)
        note_payload = {
            "target_type": "stable_candidate",
            "target_id": candidate_id,
            "content": str(payload.get("decision_reason") or "加入稳定池").strip() or "加入稳定池",
            "labels": ["stable_pool"],
            "decision_status": "approved",
            "decision_reason": _optional_str(payload.get("decision_reason")),
            "linked_parameter_group": candidate_id,
        }
        status, body = self._handle_create_research_note(note_payload)
        return status, {"stable_candidate_id": candidate_id, "chosen_run_id": chosen_run_id, **body}

    def _handle_run_stable_candidate_execution_verification(self, candidate_id: str, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("stable_candidate_id must not be empty")
        source_run_id = _require_str(payload, "source_run_id")
        execution_timeframe = str(payload.get("execution_timeframe", "5m")).strip().lower()
        execution_snapshot_id = _require_str(payload, "execution_snapshot_id")
        group_detail = load_parameter_group_detail(
            FileRunRepository(self.server.data_dir),
            group_key=candidate_id,
            data_dir=self.server.data_dir,
        )
        if source_run_id not in {run.run_id for run in group_detail.runs}:
            raise ValueError("source_run_id must belong to the stable candidate parameter group")
        execution_snapshot = _load_snapshot(self.server.data_dir, execution_snapshot_id)
        result = run_execution_verification_workflow(
            dataset_repository=FileDatasetRepository(self.server.data_dir),
            feature_repository=FileFeatureRepository(self.server.data_dir),
            run_repository=FileRunRepository(self.server.data_dir),
            request=ExecutionVerificationRequest(
                stable_candidate_id=candidate_id,
                parent_run_id=source_run_id,
                execution_snapshot=execution_snapshot,
                execution_timeframe=execution_timeframe,
                run_id=_optional_str(payload.get("run_id")),
            ),
        )
        return (
            HTTPStatus.OK,
            {
                "task_id": f"task:{result.run_id}",
                "task_status": "success",
                "stable_candidate_id": candidate_id,
                "parent_run_id": source_run_id,
                "verification_run_id": result.run_id,
                "execution_timeframe": result.execution_timeframe,
                "strategy_timeframe": result.strategy_timeframe,
                "signal_count": result.signal_count,
                "order_count": result.order_count,
                "fill_count": result.fill_count,
                "warning_count": result.warning_count,
                "trade_count": result.trade_count,
                "metrics": result.metrics.as_dict(),
            },
        )

    def _handle_run_stable_candidate_execution_filter_experiment(self, candidate_id: str, payload: dict[str, object]) -> tuple[HTTPStatus, dict[str, object]]:
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("stable_candidate_id must not be empty")
        source_run_id = _require_str(payload, "source_run_id")
        run_repository = FileRunRepository(self.server.data_dir)
        source_manifest = run_repository.load_manifest(source_run_id)
        resolved = source_manifest.resolved_config_json
        if resolved.get("run_type") != "execution_verification":
            raise ValueError("source_run_id must point to a 5m execution verification run")
        if str(resolved.get("stable_candidate_id") or "") != candidate_id:
            raise ValueError("source_run_id must belong to the stable candidate")
        parent_run_id = str(resolved.get("parent_run_id") or "")
        if not parent_run_id:
            raise ValueError("execution verification run missing parent_run_id")
        execution_snapshot = _load_snapshot(self.server.data_dir, source_manifest.dataset_snapshot_id)
        execution_timeframe = str(resolved.get("execution_timeframe") or execution_snapshot.timeframe).strip().lower()
        signal_filter_sets = _build_signal_filter_sets(payload)
        batch_id = str(payload.get("batch_id") or f"ev-filter-experiment-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}")
        result = self._submit_execution_filter_experiment_batch(
            batch_id=batch_id,
            stable_candidate_id=candidate_id,
            source_run_id=source_run_id,
            parent_run_id=parent_run_id,
            execution_snapshot=execution_snapshot,
            execution_timeframe=execution_timeframe,
            signal_filter_sets=signal_filter_sets,
        )
        body = {
            "task_id": result["task_id"],
            "task_status": "pending",
            "batch_id": batch_id,
            "source_run_id": source_run_id,
            "parent_run_id": parent_run_id,
            "execution_timeframe": execution_timeframe,
            "planned_experiment_count": 1,
            "planned_run_count": len(signal_filter_sets),
            "filter_set_count": len(signal_filter_sets),
            "filter_sets": list(signal_filter_sets),
        }
        return HTTPStatus.ACCEPTED, body

    def _submit_execution_filter_experiment_batch(
        self,
        *,
        batch_id: str,
        stable_candidate_id: str,
        source_run_id: str,
        parent_run_id: str,
        execution_snapshot: DatasetSnapshot,
        execution_timeframe: str,
        signal_filter_sets: tuple[dict[str, object], ...],
    ) -> dict[str, object]:
        if not signal_filter_sets:
            raise ValueError("At least one signal filter set is required")
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        if batch_id in batch_repository.list_batch_ids():
            raise FileExistsError(f"Parameter experiment batch already exists: {batch_id}")
        task = TaskRecord(
            task_id=f"execution-filter-experiment-batch:{batch_id}",
            task_kind="execution_filter_experiment_batch",
        )
        experiment_id = f"{batch_id}-exp-01-{execution_snapshot.dataset_snapshot_id.split('-')[-1][:8]}"
        batch = ExperimentBatch(
            batch_id=batch_id,
            strategy_name="ema_pullback_atr_v2",
            dataset_snapshot_ids=(execution_snapshot.dataset_snapshot_id,),
            validation_split_id=f"execution-filter:{source_run_id}",
            metric_policy_id="metrics_daily_365_v1",
            benchmark_policy_version="buy_and_hold_v1",
            search_type=SearchType.GRID,
            search_space_json={
                "run_type": "execution_filter_experiment",
                "source_run_id": source_run_id,
                "parent_run_id": parent_run_id,
                "stable_candidate_id": stable_candidate_id,
                "execution_timeframe": execution_timeframe,
                "signal_filter_sets": list(signal_filter_sets),
                "planned_run_count": len(signal_filter_sets),
            },
            base_config_uri="memory://execution-filter-experiments/base-config.json",
            seed_policy=SeedPolicy.GLOBAL_RANDOM,
            seed=None,
            experiment_ids=(experiment_id,),
        )
        experiment = ParameterExperiment(
            experiment_id=experiment_id,
            strategy_name="ema_pullback_atr_v2",
            dataset_bundle_id=execution_snapshot.dataset_snapshot_id,
            validation_split_id=batch.validation_split_id,
            metric_policy_id=batch.metric_policy_id,
            benchmark_policy_version=batch.benchmark_policy_version,
            benchmark_config_uri="memory://execution-filter-experiments/benchmark-config.json",
            search_type=SearchType.GRID,
            search_space_json=dict(batch.search_space_json),
            base_config_uri=batch.base_config_uri,
            seed_policy=SeedPolicy.GLOBAL_RANDOM,
            seed=None,
        )
        task_repository = FileTaskRepository(self.server.data_dir)
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        task_repository.save_task(task)
        batch_repository.save_batch(batch)
        experiment_repository.save_experiment(experiment)
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
                "planned_experiment_count": 1,
                "planned_run_count": len(signal_filter_sets),
                "updated_at": task.updated_at.isoformat(),
            },
        )
        experiment_repository.save_execution_index(
            experiment_id,
            {
                "experiment_id": experiment_id,
                "task_id": task.task_id,
                "status": task.status.value,
                "run_ids": [],
                "child_task_ids": [],
                "failed_child_task_ids": [],
                "planned_run_count": len(signal_filter_sets),
                "updated_at": task.updated_at.isoformat(),
            },
        )
        worker = threading.Thread(
            target=self._run_execution_filter_experiment_batch_in_background,
            kwargs={
                "batch_id": batch_id,
                "experiment_id": experiment_id,
                "task_id": task.task_id,
                "stable_candidate_id": stable_candidate_id,
                "source_run_id": source_run_id,
                "parent_run_id": parent_run_id,
                "execution_snapshot_id": execution_snapshot.dataset_snapshot_id,
                "execution_timeframe": execution_timeframe,
                "signal_filter_sets": signal_filter_sets,
            },
            daemon=True,
            name=f"execution-filter-experiment-batch:{batch_id}",
        )
        self.server.background_threads[task.task_id] = worker
        worker.start()
        return {"task_id": task.task_id}

    def _run_execution_filter_experiment_batch_in_background(
        self,
        *,
        batch_id: str,
        experiment_id: str,
        task_id: str,
        stable_candidate_id: str,
        source_run_id: str,
        parent_run_id: str,
        execution_snapshot_id: str,
        execution_timeframe: str,
        signal_filter_sets: tuple[dict[str, object], ...],
    ) -> None:
        task_repository = FileTaskRepository(self.server.data_dir)
        batch_repository = FileExperimentBatchRepository(self.server.data_dir)
        experiment_repository = FileParameterExperimentRepository(self.server.data_dir)
        run_repository = FileRunRepository(self.server.data_dir)
        dataset_repository = FileDatasetRepository(self.server.data_dir)
        feature_repository = FileFeatureRepository(self.server.data_dir)
        task = task_repository.load_task(task_id)
        running_task = TaskRecord(
            task_id=task.task_id,
            task_kind=task.task_kind,
            status=TaskStatus.RUNNING,
            created_at=task.created_at,
            updated_at=datetime.now(UTC),
        )
        task_repository.save_task(running_task)
        run_ids: list[str] = []
        failed_run_ids: list[str] = []
        snapshot = _load_snapshot(self.server.data_dir, execution_snapshot_id)
        for index, signal_filter_set in enumerate(signal_filter_sets, start=1):
            filter_set_id = str(signal_filter_set.get("filter_set_id") or f"filter-{index:02d}")
            run_id = f"{experiment_id}-run-{index:03d}-{_safe_id_part(filter_set_id)}"
            try:
                result = run_execution_verification_workflow(
                    dataset_repository=dataset_repository,
                    feature_repository=feature_repository,
                    run_repository=run_repository,
                    request=ExecutionVerificationRequest(
                        stable_candidate_id=stable_candidate_id,
                        parent_run_id=parent_run_id,
                        execution_snapshot=snapshot,
                        execution_timeframe=execution_timeframe,
                        run_id=run_id,
                        signal_filter_set=signal_filter_set,
                        run_type="execution_filter_experiment",
                        source_run_id=source_run_id,
                    ),
                )
                run_ids.append(result.run_id)
            except Exception:
                failed_run_ids.append(run_id)
            experiment_repository.save_execution_index(
                experiment_id,
                {
                    "experiment_id": experiment_id,
                    "task_id": running_task.task_id,
                    "status": TaskStatus.RUNNING.value,
                    "run_ids": run_ids,
                    "child_task_ids": [],
                    "failed_child_task_ids": failed_run_ids,
                    "planned_run_count": len(signal_filter_sets),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            batch_repository.save_execution_index(
                batch_id,
                {
                    "batch_id": batch_id,
                    "task_id": running_task.task_id,
                    "status": TaskStatus.RUNNING.value,
                    "dataset_snapshot_ids": [execution_snapshot_id],
                    "experiment_ids": [experiment_id],
                    "run_ids": run_ids,
                    "child_task_ids": [],
                    "failed_experiment_ids": [experiment_id] if failed_run_ids else [],
                    "planned_experiment_count": 1,
                    "planned_run_count": len(signal_filter_sets),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        final_status = TaskStatus.FAILED if failed_run_ids else TaskStatus.SUCCESS
        final_task = TaskRecord(
            task_id=running_task.task_id,
            task_kind=running_task.task_kind,
            status=final_status,
            created_at=running_task.created_at,
            updated_at=datetime.now(UTC),
        )
        task_repository.save_task(final_task)
        experiment_repository.save_execution_index(
            experiment_id,
            {
                "experiment_id": experiment_id,
                "task_id": final_task.task_id,
                "status": final_status.value,
                "run_ids": run_ids,
                "child_task_ids": [],
                "failed_child_task_ids": failed_run_ids,
                "planned_run_count": len(signal_filter_sets),
                "updated_at": final_task.updated_at.isoformat(),
            },
        )
        batch_repository.save_execution_index(
            batch_id,
            {
                "batch_id": batch_id,
                "task_id": final_task.task_id,
                "status": final_status.value,
                "dataset_snapshot_ids": [execution_snapshot_id],
                "experiment_ids": [experiment_id],
                "run_ids": run_ids,
                "child_task_ids": [],
                "failed_experiment_ids": [experiment_id] if failed_run_ids else [],
                "planned_experiment_count": 1,
                "planned_run_count": len(signal_filter_sets),
                "updated_at": final_task.updated_at.isoformat(),
            },
        )

    def _parameter_group_key_for_run(self, run_id: str) -> str:
        run_repository = FileRunRepository(self.server.data_dir)
        research_workspace = build_parameter_research_workspace(run_repository, data_dir=self.server.data_dir)
        for group in research_workspace.parameter_groups:
            if run_id in group.run_ids:
                return group.group_key
        raise FileNotFoundError(f"Parameter group not found for run: {run_id}")

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
        if isinstance(exc, CLIENT_DISCONNECT_ERRORS):
            return
        if isinstance(exc, FileNotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, FileExistsError):
            status = HTTPStatus.CONFLICT
        elif isinstance(exc, (ValueError, KeyError)):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        with contextlib.suppress(*CLIENT_DISCONNECT_ERRORS):
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


def _build_batch_validation_split_factory(
    *,
    payload: dict[str, object],
    batch_id: str,
):
    mode = str(payload.get("validation_split_mode", "none"))
    if mode in {"none", ""}:
        return None
    warmup_bars = int(payload.get("warmup_bars", 0))
    if warmup_bars < 0:
        raise ValueError("warmup_bars must be >= 0")

    if mode == "auto_ratio":
        ratio = float(payload.get("oos_ratio", 0.3))
        if ratio <= 0 or ratio >= 1:
            raise ValueError("oos_ratio must be in (0, 1)")

        def factory(snapshot: DatasetSnapshot) -> ValidationSplit:
            split_at = _split_timestamp_by_ratio(snapshot=snapshot, oos_ratio=ratio)
            return ValidationSplit(
                validation_split_id=f"validation:{batch_id}:{snapshot.dataset_snapshot_id}:auto-{int(ratio * 100)}",
                target_type=ValidationTargetType.DATASET_SNAPSHOT,
                target_id=snapshot.dataset_snapshot_id,
                warmup_bars=warmup_bars,
                is_start=snapshot.time_range_start,
                is_end=split_at,
                oos_start=split_at,
                oos_end=snapshot.time_range_end + _snapshot_bar_delta(snapshot),
            )

        return factory

    if mode == "manual":
        boundaries = {
            "is_start": payload.get("is_start"),
            "is_end": payload.get("is_end"),
            "oos_start": payload.get("oos_start"),
            "oos_end": payload.get("oos_end"),
        }
        if any(value in {None, ""} for value in boundaries.values()):
            joined = ", ".join(sorted(boundaries))
            raise ValueError(f"Manual validation split requires all of: {joined}")

        def factory(snapshot: DatasetSnapshot) -> ValidationSplit:
            return ValidationSplit(
                validation_split_id=f"validation:{batch_id}:{snapshot.dataset_snapshot_id}:manual",
                target_type=ValidationTargetType.DATASET_SNAPSHOT,
                target_id=snapshot.dataset_snapshot_id,
                warmup_bars=warmup_bars,
                is_start=_parse_datetime(str(payload["is_start"])),
                is_end=_parse_datetime(str(payload["is_end"])),
                oos_start=_parse_datetime(str(payload["oos_start"])),
                oos_end=_parse_datetime(str(payload["oos_end"])),
            )

        return factory

    raise ValueError("validation_split_mode must be one of: none, auto_ratio, manual")


def _split_timestamp_by_ratio(*, snapshot: DatasetSnapshot, oos_ratio: float) -> datetime:
    duration = snapshot.time_range_end - snapshot.time_range_start
    if duration.total_seconds() <= 0:
        raise ValueError("Dataset snapshot time range must be positive for auto validation split")
    return snapshot.time_range_start + duration * (1 - oos_ratio)


def _snapshot_bar_delta(snapshot: DatasetSnapshot) -> timedelta:
    normalized = snapshot.timeframe.strip().lower()
    unit = normalized[-1:] if normalized else ""
    try:
        amount = int(normalized[:-1])
    except ValueError:
        return timedelta(0)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)
    return timedelta(0)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: object | None) -> datetime | None:
    if value in {None, ""}:
        return None
    return _parse_datetime(str(value))


def _run_binance_kline_stream(data_dir: Path, spec: LiveKlineStreamSpec) -> None:
    cache = FileLiveKlineCache(data_dir)
    asyncio.run(
        stream_binance_usdm_klines(
            cache=cache,
            specs=[spec],
            on_closed_candle=lambda closed_spec, candle: _auto_tick_paper_sessions_for_closed_candle(
                data_dir,
                cache,
                closed_spec,
                candle,
            ),
        )
    )


def _auto_tick_paper_sessions_for_closed_candle(
    data_dir: Path,
    cache: FileLiveKlineCache,
    spec: LiveKlineStreamSpec,
    candle: object,
) -> None:
    if spec.timeframe != "5m":
        return
    repository = FilePaperTradingRepository(data_dir)
    matched_sessions = [
        session
        for session in repository.list_sessions()
        if session.status == "active"
        and session.symbol == spec.symbol
        and _exchange_alias(session.exchange) == _exchange_alias(spec.exchange)
        and session.market_type == spec.market_type.value
        and session.price_type == spec.price_type.value
        and session.execution_timeframe == spec.timeframe
    ]
    for session in matched_sessions:
        try:
            result = tick_paper_session_workflow(
                paper_repository=repository,
                feature_repository=FileFeatureRepository(data_dir),
                market_data_client=PaperLocalKlineMarketDataClient(
                    data_dir=data_dir,
                    live_cache=cache,
                    allow_rest_fallback=False,
                ),
                request=TickPaperSessionRequest(session_id=session.session_id),
            )
            cache.save_status(
                spec,
                {
                    "auto_tick_status": "success",
                    "auto_tick_session_id": session.session_id,
                    "auto_tick_at": datetime.now(UTC).isoformat(),
                    "auto_tick_last_execution_bar_time": (
                        result.session.checkpoint.last_execution_bar_time.isoformat()
                        if result.session.checkpoint.last_execution_bar_time
                        else None
                    ),
                    "auto_tick_execution_bar_count": result.session.checkpoint.execution_bar_count,
                    "auto_tick_new_execution_bars": result.execution_bar_count,
                    "auto_tick_order_count": result.order_count,
                    "auto_tick_fill_count": result.fill_count,
                    "auto_tick_closed_trade_count": result.closed_trade_count,
                    "auto_tick_error": None,
                },
            )
        except Exception as exc:  # pragma: no cover - exercised by live runtime
            cache.save_status(
                spec,
                {
                    "auto_tick_status": "error",
                    "auto_tick_session_id": session.session_id,
                    "auto_tick_at": datetime.now(UTC).isoformat(),
                    "auto_tick_error": f"{type(exc).__name__}: {exc}",
                },
            )


def _exchange_alias(exchange: str) -> str:
    return "binanceusdm" if exchange in {"binance", "binanceusdm"} else exchange


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
    risk_pct_per_trade = _optional_number(payload.get("risk_pct_per_trade"))
    qty_by_policy: dict[str, float] = {}
    cash_allocation_pct_by_policy: dict[str, float] = {}
    risk_pct_per_trade_by_policy: dict[str, float] = {}

    if qty_policy_ref == DEFAULT_QTY_POLICY_REF:
        if risk_pct_per_trade is not None:
            raise ValueError("risk_pct_per_trade only supports risk sizing qty_policy_ref")
        if qty is not None:
            raise ValueError("qty is not supported with qty_policy_ref=percent_of_cash")
        if cash_allocation_pct is None:
            cash_allocation_pct = DEFAULT_CASH_ALLOCATION_PCT
        cash_allocation_pct_by_policy[qty_policy_ref] = cash_allocation_pct
    elif qty_policy_ref == RISK_PCT_OF_EQUITY_POLICY_REF:
        if cash_allocation_pct is not None:
            raise ValueError("cash_allocation_pct only supports qty_policy_ref=percent_of_cash")
        if qty is not None:
            raise ValueError("qty is not supported with qty_policy_ref=risk_pct_of_equity")
        if risk_pct_per_trade is None:
            raise KeyError("risk_pct_per_trade")
        risk_pct_per_trade_by_policy[qty_policy_ref] = risk_pct_per_trade
    elif qty_policy_ref == RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF:
        if qty is not None:
            raise ValueError("qty is not supported with qty_policy_ref=risk_pct_of_cash_allocation")
        if cash_allocation_pct is None:
            cash_allocation_pct = DEFAULT_CASH_ALLOCATION_PCT
        if risk_pct_per_trade is None:
            raise KeyError("risk_pct_per_trade")
        cash_allocation_pct_by_policy[qty_policy_ref] = cash_allocation_pct
        risk_pct_per_trade_by_policy[qty_policy_ref] = risk_pct_per_trade
    elif qty is not None:
        qty_by_policy[qty_policy_ref] = qty
    else:
        if cash_allocation_pct is not None:
            raise ValueError("cash_allocation_pct only supports qty_policy_ref=percent_of_cash")
        if risk_pct_per_trade is not None:
            raise ValueError("risk_pct_per_trade only supports risk sizing qty_policy_ref")
        raise KeyError("Either qty, cash_allocation_pct, or risk_pct_per_trade must be provided")

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
            risk_pct_per_trade_by_policy=risk_pct_per_trade_by_policy,
        ),
    )


def _build_strategy_params_from_payload(
    payload: dict[str, object],
    *,
    strategy_name: str,
    qty_policy_ref: str,
) -> dict[str, object]:
    if strategy_name == "ema_pullback_atr_v2":
        strategy_params = {
            "strategy_name": "ema_pullback_atr_v2",
            "trend_fast_period": int(payload.get("trend_fast_period", 8)),
            "trend_slow_period": int(payload.get("trend_slow_period", 34)),
            "atr_entry_tolerance": float(payload.get("atr_entry_tolerance", 0.5)),
            "atr_stop_mult": float(payload.get("atr_stop_mult", 1.5)),
            "risk_reward_ratio": float(payload.get("risk_reward_ratio", 1.5)),
            "entry_ema_period": int(payload.get("entry_ema_period", 21)),
            "atr_period": int(payload.get("atr_period", 14)),
            "min_atr_pct_of_price": float(payload.get("min_atr_pct_of_price", 0.002)),
            "min_stop_pct": float(payload.get("min_stop_pct", 0.003)),
            "qty_policy_ref": qty_policy_ref,
        }
        risk_pct_per_trade = _optional_number(payload.get("risk_pct_per_trade"))
        if qty_policy_ref in {RISK_PCT_OF_EQUITY_POLICY_REF, RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF} and risk_pct_per_trade is not None:
            strategy_params["risk_pct_per_trade"] = risk_pct_per_trade
        cash_allocation_pct = _optional_number(payload.get("cash_allocation_pct"))
        if qty_policy_ref == RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF and cash_allocation_pct is not None:
            strategy_params["cash_allocation_pct"] = cash_allocation_pct
        return strategy_params
    if strategy_name != "ema_crossover":
        raise ValueError(f"Unsupported strategy_name: {strategy_name}")
    return {
        "strategy_name": "ema_crossover",
        "fast_period": int(payload.get("fast_period", 2)),
        "slow_period": int(payload.get("slow_period", 3)),
        "qty_policy_ref": qty_policy_ref,
    }


def _require_int_tuple(payload: dict[str, object], field_name: str) -> tuple[int, ...]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    return tuple(int(item) for item in value)


def _optional_int_tuple(payload: dict[str, object], field_name: str) -> tuple[int, ...]:
    value = payload.get(field_name)
    if value is None:
        return ()
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


def _optional_float_tuple(payload: dict[str, object], field_name: str) -> tuple[float, ...]:
    value = payload.get(field_name)
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    return tuple(float(item) for item in value)


def _optional_dict_tuple(payload: dict[str, object], field_name: str) -> tuple[dict[str, object], ...]:
    value = payload.get(field_name)
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    items: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} must contain only objects")
        items.append(dict(item))
    return tuple(items)


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


def _optional_query_decision_status(query: dict[str, list[str]], field_name: str) -> str | None:
    value = _first_query_value(query, field_name)
    if value is None:
        return None
    return _normalize_decision_status(value)


def _normalize_labels(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("labels must be an array")
    labels = tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    return labels


def _normalize_decision_status(value: object | None) -> str:
    if value is None:
        return "candidate"
    decision_status = str(value).strip()
    if decision_status not in RESEARCH_NOTE_DECISION_STATUSES:
        allowed = ", ".join(sorted(RESEARCH_NOTE_DECISION_STATUSES))
        raise ValueError(f"decision_status must be one of {allowed}")
    return decision_status


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_id_part(value: object) -> str:
    text = str(value).strip().lower()
    chars = [char if char.isalnum() else "-" for char in text]
    compact = "-".join(part for part in "".join(chars).split("-") if part)
    return compact[:48] or "item"


def _optional_float(value: object | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _build_signal_filter_sets(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw_sets = payload.get("signal_filter_sets")
    if raw_sets is not None:
        if not isinstance(raw_sets, list):
            raise ValueError("signal_filter_sets must be an array")
        return tuple(_normalize_signal_filter_set(item) for item in raw_sets)

    mode = str(payload.get("mode", "single")).strip() or "single"
    selected = payload.get("filter_types")
    filter_types = (
        [str(item) for item in selected]
        if isinstance(selected, list) and selected
        else ["higher_timeframe_trend", "atr_percentile", "adx"]
    )
    filter_sets = [_default_signal_filter_set(filter_type) for filter_type in filter_types]
    if mode in {"stacked", "recommended"} and len(filter_sets) > 1:
        stacked_filters = [signal_filter for filter_set in filter_sets for signal_filter in filter_set["filters"]]
        filter_sets.append(
            {
                "filter_set_id": "stacked_core",
                "label": "stacked-core",
                "mode": "stacked",
                "filters": stacked_filters,
            }
        )
    return tuple(_normalize_signal_filter_set(item) for item in filter_sets)


def _default_signal_filter_set(filter_type: str) -> dict[str, object]:
    if filter_type == "higher_timeframe_trend":
        return {
            "filter_set_id": "htf-trend-ema50-200",
            "label": "htf-trend",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "higher_timeframe_trend",
                    "enabled": True,
                    "params": {"ema_fast": 50, "ema_slow": 200, "mode": "direction_aligned"},
                }
            ],
        }
    if filter_type == "atr_percentile":
        return {
            "filter_set_id": "atr-p20-80",
            "label": "atr-p20-80",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "atr_percentile",
                    "enabled": True,
                    "params": {"atr_period": 14, "lookback_bars": 200, "min_percentile": 20, "max_percentile": 80},
                }
            ],
        }
    if filter_type == "adx":
        return {
            "filter_set_id": "adx-20",
            "label": "adx-20",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "adx",
                    "enabled": True,
                    "params": {"adx_period": 14, "min_adx": 20},
                }
            ],
        }
    if filter_type == "pre_entry_momentum_3":
        return {
            "filter_set_id": "pre-mom3-nonnegative",
            "label": "pre-mom3>=0",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "pre_entry_momentum",
                    "enabled": True,
                    "params": {"lookback_bars": 3, "min_momentum_pct": 0.0},
                }
            ],
        }
    if filter_type == "pre_entry_momentum_5":
        return {
            "filter_set_id": "pre-mom5-nonnegative",
            "label": "pre-mom5>=0",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "pre_entry_momentum",
                    "enabled": True,
                    "params": {"lookback_bars": 5, "min_momentum_pct": 0.0},
                }
            ],
        }
    if filter_type == "consecutive_move":
        return {
            "filter_set_id": "consecutive-move-1",
            "label": "consecutive>=1",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "consecutive_move",
                    "enabled": True,
                    "params": {"min_consecutive": 1},
                }
            ],
        }
    if filter_type == "local_range_position":
        return {
            "filter_set_id": "local-position-gte-05",
            "label": "local-pos>=0.5",
            "mode": "single",
            "filters": [
                {
                    "filter_type": "local_range_position",
                    "enabled": True,
                    "params": {"lookback_bars": 20, "min_position": 0.5},
                }
            ],
        }
    if filter_type == "early_fail_proxy_core":
        return {
            "filter_set_id": "early-fail-proxy-core",
            "label": "early-fail-proxy-core",
            "mode": "stacked",
            "filters": [
                {
                    "filter_type": "pre_entry_momentum",
                    "enabled": True,
                    "params": {"lookback_bars": 3, "min_momentum_pct": 0.0},
                },
                {
                    "filter_type": "consecutive_move",
                    "enabled": True,
                    "params": {"min_consecutive": 1},
                },
                {
                    "filter_type": "local_range_position",
                    "enabled": True,
                    "params": {"lookback_bars": 20, "min_position": 0.5},
                },
            ],
        }
    raise ValueError(f"Unsupported filter_type: {filter_type}")


def _normalize_signal_filter_set(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("signal_filter_sets entries must be objects")
    filters = value.get("filters")
    if not isinstance(filters, list) or not filters:
        raise ValueError("signal_filter_set.filters must be a non-empty array")
    return {
        "filter_set_id": str(value.get("filter_set_id") or value.get("label") or "filter-set"),
        "label": str(value.get("label") or value.get("filter_set_id") or "filter-set"),
        "mode": str(value.get("mode") or "single"),
        "filters": [_normalize_signal_filter(item) for item in filters],
    }


def _normalize_signal_filter(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("signal filter must be an object")
    filter_type = str(value.get("filter_type") or "")
    if filter_type not in {
        "higher_timeframe_trend",
        "atr_percentile",
        "adx",
        "pre_entry_momentum",
        "consecutive_move",
        "local_range_position",
        "entry_context_exclusion",
    }:
        raise ValueError(f"Unsupported signal filter type: {filter_type}")
    params = value.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("signal filter params must be an object")
    return {
        "filter_type": filter_type,
        "enabled": bool(value.get("enabled", True)),
        "params": params,
    }


def _matches_filter_result_signature(base_group: object, row: ParameterLabRow) -> bool:
    fields = (
        "strategy_name",
        "symbol",
        "timeframe",
        "fast_period",
        "slow_period",
        "trend_fast_period",
        "trend_slow_period",
        "entry_ema_period",
        "atr_period",
        "atr_entry_tolerance",
        "atr_stop_mult",
        "risk_reward_ratio",
        "qty_policy_ref",
        "cash_allocation_pct",
        "risk_pct_per_trade",
        "leverage",
    )
    return all(getattr(base_group, field) == getattr(row, field) for field in fields)


def _build_filter_result_group(filter_summary: str, rows: list[ParameterLabRow], *, base_group: object) -> dict[str, object]:
    run_count = len(rows)
    oos_values = [float(row.oos_total_return) for row in rows if row.oos_total_return is not None]
    total_values = [float(row.total_return) for row in rows]
    drawdowns = [float(row.max_drawdown) for row in rows]
    profit_factors = [float(row.profit_factor) for row in rows if row.profit_factor is not None]
    trade_counts = [int(row.trade_count) for row in rows]
    oos_trade_counts = [int(row.oos_trade_count) for row in rows if row.oos_trade_count is not None]
    avg_oos = sum(oos_values) / len(oos_values) if oos_values else None
    avg_total = sum(total_values) / run_count if run_count else None
    avg_drawdown = sum(drawdowns) / run_count if run_count else None
    worst_drawdown = max(drawdowns) if drawdowns else None
    avg_profit_factor = sum(profit_factors) / len(profit_factors) if profit_factors else None
    min_trade_count = min(trade_counts) if trade_counts else None
    min_oos_trade_count = min(oos_trade_counts) if oos_trade_counts else None
    base_avg_oos = getattr(base_group, "avg_oos_total_return", None)
    base_avg_drawdown = getattr(base_group, "avg_max_drawdown", None)
    base_avg_profit_factor = getattr(base_group, "avg_profit_factor", None)
    base_min_trade_count = getattr(base_group, "min_trade_count", None)
    return {
        "filter_summary": filter_summary,
        "run_count": run_count,
        "snapshot_count": len({row.dataset_snapshot_id for row in rows}),
        "avg_total_return": avg_total,
        "avg_oos_total_return": avg_oos,
        "avg_oos_delta": (avg_oos - float(base_avg_oos)) if avg_oos is not None and base_avg_oos is not None else None,
        "avg_max_drawdown": avg_drawdown,
        "avg_drawdown_delta": (avg_drawdown - float(base_avg_drawdown)) if avg_drawdown is not None and base_avg_drawdown is not None else None,
        "worst_max_drawdown": worst_drawdown,
        "avg_profit_factor": avg_profit_factor,
        "avg_profit_factor_delta": (
            avg_profit_factor - float(base_avg_profit_factor)
            if avg_profit_factor is not None and base_avg_profit_factor is not None
            else None
        ),
        "min_trade_count": min_trade_count,
        "min_oos_trade_count": min_oos_trade_count,
        "trade_retention": (
            (float(min_trade_count) / float(base_min_trade_count))
            if min_trade_count is not None and base_min_trade_count
            else None
        ),
        "run_ids": [row.run_id for row in sorted(rows, key=lambda item: item.created_at, reverse=True)],
    }


def _build_research_note_id() -> str:
    return f"note-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"


def _readmodel_signature(data_dir: Path) -> tuple[int, int]:
    paths = [
        data_dir / "runs",
        data_dir / "experiments",
        data_dir / "experiment_batches",
    ]
    file_count = 0
    latest_mtime_ns = 0
    for root in paths:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            file_count += 1
            latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
    return file_count, latest_mtime_ns


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
    if target_type in {"parameter_group", "research_candidate", "stable_candidate"}:
        if "|" in target_id:
            _ = load_parameter_group_detail(
                FileRunRepository(data_dir),
                group_key=target_id,
                data_dir=data_dir,
            )
            return
        batch_id = target_id.split(":", 1)[0].strip()
        try:
            _ = FileExperimentBatchRepository(data_dir).load_batch(batch_id)
            return
        except FileNotFoundError:
            _ = load_parameter_group_detail(
                FileRunRepository(data_dir),
                group_key=target_id,
                data_dir=data_dir,
            )
        return
    raise ValueError("target_type must be one of run, parameter_experiment, parameter_experiment_batch, parameter_group, research_candidate, stable_candidate")


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
