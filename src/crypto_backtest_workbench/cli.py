"""CLI entry points for Phase 1 workflows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from crypto_backtest_workbench import __version__
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
    ValidationSplit,
    ValidationTargetType,
)

DEFAULT_QTY_POLICY_REF = "percent_of_cash"
DEFAULT_CASH_ALLOCATION_PCT = 100.0
RISK_PCT_OF_EQUITY_POLICY_REF = "risk_pct_of_equity"
RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF = "risk_pct_of_cash_allocation"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cbw")
    parser.add_argument("--version", action="store_true", help="Print package version.")

    subparsers = parser.add_subparsers(dest="command")

    scaffold = subparsers.add_parser("scaffold", help="Print the Phase 1 scaffold layout.")
    scaffold.add_argument(
        "--json",
        action="store_true",
        help="Print scaffold layout as JSON.",
    )

    ingest = subparsers.add_parser("ingest", help="Fetch candles and persist a dataset snapshot.")
    ingest.add_argument("--exchange", required=True)
    ingest.add_argument("--symbol", required=True)
    ingest.add_argument("--timeframe", required=True)
    ingest.add_argument("--since", required=True, help="ISO8601 timestamp.")
    ingest.add_argument("--until", help="ISO8601 timestamp.")
    ingest.add_argument("--repository-root", default=".")
    ingest.add_argument("--data-dir")
    ingest.add_argument("--market-type", default=MarketType.LINEAR_USDT_PERPETUAL.value)
    ingest.add_argument("--price-type", default=PriceType.LAST.value)
    ingest.add_argument("--limit", type=int, default=1000)
    ingest.add_argument(
        "--exchange-options-json",
        help="JSON object passed to the ccxt exchange constructor.",
    )
    ingest.add_argument(
        "--extra-params-json",
        help="JSON object forwarded to fetch_ohlcv params.",
    )
    ingest.add_argument(
        "--keep-open-last-candle",
        action="store_true",
        help="Keep the last still-open candle instead of dropping it.",
    )

    run_ema = subparsers.add_parser("run-ema", help="Run the Phase 1 EMA strategy on a stored snapshot.")
    run_ema.add_argument("--snapshot-id", required=True)
    run_ema.add_argument("--run-id", required=True)
    run_ema.add_argument("--repository-root", default=".")
    run_ema.add_argument("--data-dir")
    run_ema.add_argument("--fast-period", type=int, required=True)
    run_ema.add_argument("--slow-period", type=int, required=True)
    run_ema.add_argument("--qty-policy-ref", default=DEFAULT_QTY_POLICY_REF)
    run_ema.add_argument("--qty", type=float)
    run_ema.add_argument("--cash-allocation-pct", type=float)
    run_ema.add_argument("--risk-pct-per-trade", type=float)
    run_ema.add_argument("--initial-cash", type=float, default=10_000.0)
    run_ema.add_argument("--leverage", type=float, default=1.0)
    run_ema.add_argument("--fee-rate", type=float, default=0.0)
    run_ema.add_argument("--slippage-bps", type=float, default=0.0)
    run_ema.add_argument("--min-notional", type=float, default=0.0)
    run_ema.add_argument("--validation-split-id", default="validation:cli")
    run_ema.add_argument("--warmup-bars", type=int, default=0)
    run_ema.add_argument("--is-start", help="ISO8601 timestamp for in-sample start.")
    run_ema.add_argument("--is-end", help="ISO8601 timestamp for in-sample end.")
    run_ema.add_argument("--oos-start", help="ISO8601 timestamp for out-of-sample start.")
    run_ema.add_argument("--oos-end", help="ISO8601 timestamp for out-of-sample end.")
    run_ema.add_argument(
        "--benchmark",
        choices=["none", "buy_and_hold"],
        default="buy_and_hold",
    )

    ui = subparsers.add_parser("ui", help="Launch the React UI with the co-hosted Python API.")
    ui.add_argument("--repository-root", default=".")
    ui.add_argument("--data-dir")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8501)
    ui.add_argument("--cors-origin", default="*")

    ui_streamlit = subparsers.add_parser("ui-streamlit", help="Launch the legacy Streamlit UI.")
    ui_streamlit.add_argument("--repository-root", default=".")
    ui_streamlit.add_argument("--data-dir")
    ui_streamlit.add_argument("--host", default="127.0.0.1")
    ui_streamlit.add_argument("--port", type=int, default=8501)

    api = subparsers.add_parser("api", help="Launch the Phase 1 HTTP API for the React workbench.")
    api.add_argument("--repository-root", default=".")
    api.add_argument("--data-dir")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--cors-origin", default="*")
    return parser


def scaffold_layout() -> dict[str, list[str]]:
    return {
        "domain": [
            "common enums and identifiers",
            "dataset snapshots and validation splits",
            "feature artifacts and cache keys",
            "execution events and run manifests",
        ],
        "engine": [
            "historical data request and ingestion service",
            "strategy interface",
            "execution policy defaults",
            "portfolio account snapshot",
            "feature cache registry",
        ],
        "jobs": [
            "single run task payload",
            "parameter experiment task payload",
            "task lifecycle record",
        ],
        "storage": [
            "artifact uri helpers",
            "dataset repository scaffold",
        ],
        "docs": [
            "implementation design",
            "reference usage",
            "phase 1 code skeleton",
        ],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return 0

    if args.command == "scaffold":
        layout = scaffold_layout()
        if args.json:
            print(json.dumps(layout, indent=2, sort_keys=True))
        else:
            print("Phase 1 scaffold:")
            for section, items in layout.items():
                print(f"- {section}")
                for item in items:
                    print(f"  - {item}")
        return 0

    if args.command == "ingest":
        return _run_command(_handle_ingest, args)

    if args.command == "run-ema":
        return _run_command(_handle_run_ema, args)

    if args.command == "ui":
        return _run_command(_handle_ui, args)

    if args.command == "ui-streamlit":
        return _run_command(_handle_ui_streamlit, args)

    if args.command == "api":
        return _run_command(_handle_api, args)

    parser.print_help()
    return 0


def _handle_ingest(args: argparse.Namespace) -> int:
    from crypto_backtest_workbench.app.workflows import ingest_dataset_workflow

    result = ingest_dataset_workflow(
        exchange=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        since=_parse_datetime(args.since),
        until=_parse_datetime(args.until) if args.until else None,
        market_type=MarketType(args.market_type),
        price_type=PriceType(args.price_type),
        repository_root=args.repository_root,
        data_dir=args.data_dir,
        limit=args.limit,
        drop_unclosed_last_candle=not args.keep_open_last_candle,
        extra_params=_parse_json_object_arg(args.extra_params_json, field_name="--extra-params-json"),
        exchange_options=_parse_json_object_arg(
            args.exchange_options_json,
            field_name="--exchange-options-json",
        ),
    )
    _print_json(
        {
            "dataset_snapshot_id": result.snapshot.dataset_snapshot_id,
            "row_count": result.snapshot.row_count,
            "snapshot_path": str(result.snapshot_path),
            "candles_path": str(result.candles_path),
            "integrity_report_path": str(result.integrity_report_path),
            "dropped_open_candle": result.dropped_open_candle,
        }
    )
    return 0


def _handle_run_ema(args: argparse.Namespace) -> int:
    from crypto_backtest_workbench.app.workflows import (
        RunBacktestWorkflowRequest,
        run_backtest_task_workflow,
    )
    from crypto_backtest_workbench.jobs import LocalTaskRunner
    from crypto_backtest_workbench.storage.repositories import (
        FileDatasetRepository,
        FileFeatureRepository,
        FileRunRepository,
    )

    data_dir = _resolve_data_dir(repository_root=args.repository_root, data_dir=args.data_dir)
    dataset_repository = FileDatasetRepository(data_dir)
    feature_repository = FileFeatureRepository(data_dir)
    run_repository = FileRunRepository(data_dir)
    runner = LocalTaskRunner()
    snapshot = _load_snapshot(data_dir, args.snapshot_id)
    validation_split = _build_validation_split(args=args, snapshot=snapshot)
    task_result = run_backtest_task_workflow(
        runner=runner,
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        run_repository=run_repository,
        request=RunBacktestWorkflowRequest(
            run_id=args.run_id,
            snapshot=snapshot,
            strategy_params={
                "fast_period": args.fast_period,
                "slow_period": args.slow_period,
                "qty_policy_ref": getattr(args, "qty_policy_ref", DEFAULT_QTY_POLICY_REF),
            },
            constraints=_build_execution_constraints(args),
            validation_split=validation_split,
            enable_buy_and_hold_benchmark=args.benchmark == "buy_and_hold",
        ),
    )
    task = task_result.task
    if task_result.output is None:
        _print_json(
            {
                "task_id": task.task_id,
                "task_status": task.status.value,
                "run_id": args.run_id,
                "dataset_snapshot_id": snapshot.dataset_snapshot_id,
                "failure_code": task.failure_code.value if task.failure_code is not None else None,
                "failure_stage": task.failure_stage,
                "failure_message": task.failure_message,
            }
        )
        return 1

    workflow_result = task_result.output.workflow_result
    execution = workflow_result.single_run_result.execution
    metrics = workflow_result.single_run_result.metrics.as_dict()
    _print_json(
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
            "persisted": _json_ready(task_result.output.persisted_paths),
        }
    )
    return 0


def _handle_ui(args: argparse.Namespace) -> int:
    from crypto_backtest_workbench.app.api import serve_ui

    return serve_ui(
        host=args.host,
        port=args.port,
        repository_root=args.repository_root,
        data_dir=args.data_dir,
        cors_origin=args.cors_origin,
    )


def _handle_ui_streamlit(args: argparse.Namespace) -> int:
    command = _build_ui_launch_command(
        python_executable=sys.executable,
        app_path=_streamlit_app_path(),
        repository_root=args.repository_root,
        data_dir=args.data_dir,
        host=args.host,
        port=args.port,
    )
    try:
        completed = subprocess.run(command, check=False)
    except KeyboardInterrupt:
        return 130
    return completed.returncode


def _handle_api(args: argparse.Namespace) -> int:
    from crypto_backtest_workbench.app.api import serve_api

    return serve_api(
        host=args.host,
        port=args.port,
        repository_root=args.repository_root,
        data_dir=args.data_dir,
        cors_origin=args.cors_origin,
    )


def _run_command(handler, args: argparse.Namespace) -> int:
    try:
        return handler(args)
    except Exception as exc:
        _print_json(
            {
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            }
        )
        return 1


def _resolve_data_dir(*, repository_root: str | Path, data_dir: str | Path | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    return Path(repository_root) / "data"


def _streamlit_app_path() -> Path:
    from crypto_backtest_workbench.app import streamlit_app

    return Path(streamlit_app.__file__).resolve()


def _build_ui_launch_command(
    *,
    python_executable: str,
    app_path: Path,
    repository_root: str | Path,
    data_dir: str | Path | None,
    host: str,
    port: int,
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "true",
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--",
        "--repository-root",
        str(repository_root),
    ]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir)])
    return command


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


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_json_object_arg(value: str | None, *, field_name: str) -> dict[str, object] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def _build_execution_constraints(args: argparse.Namespace):
    from crypto_backtest_workbench.engine.execution import ExecutionConstraints

    qty_policy_ref = getattr(args, "qty_policy_ref", DEFAULT_QTY_POLICY_REF)
    qty = getattr(args, "qty", None)
    cash_allocation_pct = getattr(args, "cash_allocation_pct", None)
    risk_pct_per_trade = getattr(args, "risk_pct_per_trade", None)
    qty_by_policy: dict[str, float] = {}
    cash_allocation_pct_by_policy: dict[str, float] = {}
    risk_pct_per_trade_by_policy: dict[str, float] = {}

    if qty_policy_ref == DEFAULT_QTY_POLICY_REF:
        if risk_pct_per_trade is not None:
            raise ValueError("risk_pct_per_trade only supports risk sizing --qty-policy-ref")
        if qty is not None:
            raise ValueError("qty is not supported with --qty-policy-ref percent_of_cash")
        if cash_allocation_pct is None:
            cash_allocation_pct = DEFAULT_CASH_ALLOCATION_PCT
        cash_allocation_pct_by_policy[qty_policy_ref] = float(cash_allocation_pct)
    elif qty_policy_ref == RISK_PCT_OF_EQUITY_POLICY_REF:
        if cash_allocation_pct is not None:
            raise ValueError("cash_allocation_pct only supports --qty-policy-ref percent_of_cash")
        if qty is not None:
            raise ValueError("qty is not supported with --qty-policy-ref risk_pct_of_equity")
        if risk_pct_per_trade is None:
            raise ValueError("--risk-pct-per-trade is required")
        risk_pct_per_trade_by_policy[qty_policy_ref] = float(risk_pct_per_trade)
    elif qty_policy_ref == RISK_PCT_OF_CASH_ALLOCATION_POLICY_REF:
        if qty is not None:
            raise ValueError("qty is not supported with --qty-policy-ref risk_pct_of_cash_allocation")
        if cash_allocation_pct is None:
            cash_allocation_pct = DEFAULT_CASH_ALLOCATION_PCT
        if risk_pct_per_trade is None:
            raise ValueError("--risk-pct-per-trade is required")
        cash_allocation_pct_by_policy[qty_policy_ref] = float(cash_allocation_pct)
        risk_pct_per_trade_by_policy[qty_policy_ref] = float(risk_pct_per_trade)
    elif qty is not None:
        qty_by_policy[qty_policy_ref] = float(qty)
    else:
        if cash_allocation_pct is not None:
            raise ValueError("cash_allocation_pct only supports --qty-policy-ref percent_of_cash")
        if risk_pct_per_trade is not None:
            raise ValueError("risk_pct_per_trade only supports risk sizing --qty-policy-ref")
        raise ValueError("Either --qty, --cash-allocation-pct, or --risk-pct-per-trade is required")

    return ExecutionConstraints(
        initial_cash=args.initial_cash,
        leverage=args.leverage,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        min_notional=args.min_notional,
        qty_by_policy=qty_by_policy,
        cash_allocation_pct_by_policy=cash_allocation_pct_by_policy,
        risk_pct_per_trade_by_policy=risk_pct_per_trade_by_policy,
    )


def _build_validation_split(
    *,
    args: argparse.Namespace,
    snapshot: DatasetSnapshot,
) -> ValidationSplit | None:
    boundaries = {
        "is_start": args.is_start,
        "is_end": args.is_end,
        "oos_start": args.oos_start,
        "oos_end": args.oos_end,
    }
    provided = [name for name, value in boundaries.items() if value is not None]
    if not provided:
        return None

    if len(provided) != len(boundaries):
        joined = ", ".join(sorted(boundaries))
        raise ValueError(f"Validation split requires all of: {joined}")

    if args.warmup_bars < 0:
        raise ValueError("--warmup-bars must be >= 0")

    return ValidationSplit(
        validation_split_id=args.validation_split_id,
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id=snapshot.dataset_snapshot_id,
        warmup_bars=args.warmup_bars,
        is_start=_parse_datetime(args.is_start),
        is_end=_parse_datetime(args.is_end),
        oos_start=_parse_datetime(args.oos_start),
        oos_end=_parse_datetime(args.oos_end),
    )


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(_json_ready(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
