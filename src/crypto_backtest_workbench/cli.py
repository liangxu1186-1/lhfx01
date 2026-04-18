"""CLI entry points for Phase 1 workflows."""

from __future__ import annotations

import argparse
import json
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
    run_ema.add_argument("--qty-policy-ref", default="fixed_notional_v1")
    run_ema.add_argument("--qty", type=float, required=True)
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
    from crypto_backtest_workbench.app.workflows import RunBacktestWorkflowRequest, run_backtest_workflow
    from crypto_backtest_workbench.engine.execution import ExecutionConstraints
    from crypto_backtest_workbench.storage.repositories import (
        FileDatasetRepository,
        FileFeatureRepository,
        FileRunRepository,
    )

    data_dir = _resolve_data_dir(repository_root=args.repository_root, data_dir=args.data_dir)
    dataset_repository = FileDatasetRepository(data_dir)
    feature_repository = FileFeatureRepository(data_dir)
    run_repository = FileRunRepository(data_dir)
    snapshot = _load_snapshot(data_dir, args.snapshot_id)
    validation_split = _build_validation_split(args=args, snapshot=snapshot)
    workflow_result = run_backtest_workflow(
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        request=RunBacktestWorkflowRequest(
            run_id=args.run_id,
            snapshot=snapshot,
            strategy_params={
                "fast_period": args.fast_period,
                "slow_period": args.slow_period,
                "qty_policy_ref": args.qty_policy_ref,
            },
            constraints=ExecutionConstraints(
                initial_cash=args.initial_cash,
                leverage=args.leverage,
                fee_rate=args.fee_rate,
                slippage_bps=args.slippage_bps,
                min_notional=args.min_notional,
                qty_by_policy={args.qty_policy_ref: args.qty},
            ),
            validation_split=validation_split,
            enable_buy_and_hold_benchmark=args.benchmark == "buy_and_hold",
        ),
    )
    persisted = run_repository.save_single_run_result(workflow_result.single_run_result)
    metrics = workflow_result.single_run_result.metrics.as_dict()
    _print_json(
        {
            "run_id": workflow_result.single_run_result.run.run_id,
            "dataset_snapshot_id": snapshot.dataset_snapshot_id,
            "feature_artifact_id": workflow_result.feature_artifact.feature_artifact_id,
            "signal_count": len(workflow_result.signals),
            "trade_count": metrics.get("trade_count"),
            "benchmark_enabled": workflow_result.single_run_result.benchmark_output is not None,
            "validation_split_id": workflow_result.single_run_result.run.validation_split_id,
            "metrics": metrics,
            "persisted": _json_ready(persisted),
        }
    )
    return 0


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
