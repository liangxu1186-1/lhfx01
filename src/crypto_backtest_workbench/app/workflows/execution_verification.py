"""Stable-pool execution verification workflow."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_backtest_workbench.app.workflows.run_backtest import (
    DEFAULT_ENGINE_VERSION,
    DEFAULT_EXECUTION_POLICY_ID,
    DEFAULT_FEE_MODEL_VERSION,
    DEFAULT_METRIC_POLICY_ID,
    DEFAULT_SLIPPAGE_MODEL_VERSION,
    build_strategy,
)
from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    DatasetSnapshot,
    MarketType,
    PriceType,
    RunManifest,
    SignalIntent,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.analytics.metrics import RunMetrics
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.features import FeaturePipeline
from crypto_backtest_workbench.engine.strategy import StrategyInput
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest, SingleRunResult
from crypto_backtest_workbench.storage.repositories import DatasetRepository, FeatureRepository, RunRepository


EXECUTION_VERIFICATION_RUN_TYPE = "execution_verification"
EXECUTION_VERIFICATION_MODEL_VERSION = "intrabar-v1"


@dataclass(slots=True, frozen=True)
class ExecutionVerificationRequest:
    stable_candidate_id: str
    parent_run_id: str
    execution_snapshot: DatasetSnapshot
    execution_timeframe: str = "5m"
    run_id: str | None = None
    signal_filter_set: dict[str, object] | None = None
    run_type: str = EXECUTION_VERIFICATION_RUN_TYPE
    source_run_id: str | None = None


@dataclass(slots=True, frozen=True)
class ExecutionVerificationResult:
    run_id: str
    parent_run_id: str
    stable_candidate_id: str
    strategy_timeframe: str
    execution_timeframe: str
    signal_count: int
    order_count: int
    fill_count: int
    warning_count: int
    trade_count: int
    metrics: RunMetrics
    single_run_result: SingleRunResult


def run_execution_verification_workflow(
    *,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    run_repository: RunRepository,
    request: ExecutionVerificationRequest,
) -> ExecutionVerificationResult:
    """Create a derived execution-verification run from a stable candidate parent run."""

    parent_run = run_repository.load_run(request.parent_run_id)
    parent_manifest = run_repository.load_manifest(request.parent_run_id)
    parent_config = parent_manifest.resolved_config_json
    if parent_config.get("run_type") == EXECUTION_VERIFICATION_RUN_TYPE:
        raise ValueError("source_run_id must point to a research run, not an execution verification run")

    strategy_timeframe = str(parent_config.get("timeframe") or "")
    if strategy_timeframe != "1h":
        raise ValueError("execution verification currently supports strategy_timeframe=1h")
    execution_timeframe = request.execution_timeframe.strip().lower()
    if execution_timeframe != "5m":
        raise ValueError("execution verification currently supports execution_timeframe=5m")
    if request.execution_snapshot.timeframe.strip().lower() != execution_timeframe:
        raise ValueError("execution snapshot timeframe must match execution_timeframe")

    strategy_params = _require_dict(parent_config.get("strategy_params"), "strategy_params")
    if request.signal_filter_set is not None:
        filters = request.signal_filter_set.get("filters", [])
        if not isinstance(filters, list):
            raise ValueError("signal_filter_set.filters must be a list")
        strategy_params["signal_filters"] = tuple(filters)
    constraints = _execution_constraints_from_config(_require_dict(parent_config.get("execution_constraints"), "execution_constraints"))
    strategy = build_strategy({"strategy_name": parent_run.strategy_name, **strategy_params})
    strategy_candles = _load_candles(snapshot_id=parent_run.dataset_snapshot_id, dataset_repository=dataset_repository)
    execution_candles = _load_candles(snapshot_id=request.execution_snapshot.dataset_snapshot_id, dataset_repository=dataset_repository)
    _validate_execution_coverage(strategy_candles=strategy_candles, execution_candles=execution_candles)

    strategy_feature_artifact = FeaturePipeline(feature_repository).materialize(
        dataset_snapshot_id=parent_run.dataset_snapshot_id,
        candles=strategy_candles,
        specs=strategy.feature_specs(),
        depends_on=(parent_run.dataset_snapshot_id,),
    )
    run_id = request.run_id or _build_execution_verification_run_id(
        parent_run_id=request.parent_run_id,
        execution_timeframe=execution_timeframe,
    )
    raw_signals = strategy.generate_signals(
        StrategyInput(
            run_id=run_id,
            symbol=request.execution_snapshot.symbol,
            timeframe=strategy_timeframe,
            feature_artifact_id=strategy_feature_artifact.feature_artifact_id,
            features_uri=strategy_feature_artifact.storage_uri,
            config={"qty_policy_ref": str(strategy_params.get("qty_policy_ref") or "percent_of_cash")},
        )
    )
    mapped_signals = _map_signals_to_execution_timeline(raw_signals, execution_candles)
    resolved_config = _build_resolved_config(
        run_id=run_id,
        parent_manifest=parent_manifest,
        execution_snapshot=request.execution_snapshot,
        stable_candidate_id=request.stable_candidate_id,
        strategy_timeframe=strategy_timeframe,
        execution_timeframe=execution_timeframe,
        signal_count=len(raw_signals),
        strategy_params=strategy_params,
        signal_filter_set=request.signal_filter_set,
        run_type=request.run_type,
        source_run_id=request.source_run_id,
    )
    execution_validation_split = _build_execution_validation_split(
        parent_run_id=request.parent_run_id,
        parent_manifest=parent_manifest,
        execution_snapshot=request.execution_snapshot,
        execution_timeframe=execution_timeframe,
        run_repository=run_repository,
    )
    validation_split_id = parent_manifest.validation_split_id
    if execution_validation_split is not None:
        validation_split_id = execution_validation_split.validation_split_id
    single_run_request = SingleRunRequest(
        run_id=run_id,
        strategy_name=parent_run.strategy_name,
        strategy_version=parent_run.strategy_version,
        dataset_snapshot_id=request.execution_snapshot.dataset_snapshot_id,
        feature_artifact_id=strategy_feature_artifact.feature_artifact_id,
        validation_split_id=validation_split_id,
        execution_policy_id=DEFAULT_EXECUTION_POLICY_ID,
        metric_policy_id=parent_manifest.metric_policy_id or DEFAULT_METRIC_POLICY_ID,
        engine_version=DEFAULT_ENGINE_VERSION,
        fee_model_version=parent_manifest.fee_model_version or DEFAULT_FEE_MODEL_VERSION,
        slippage_model_version=parent_manifest.slippage_model_version or DEFAULT_SLIPPAGE_MODEL_VERSION,
        fee_model_params_json=dict(parent_manifest.fee_model_params_json),
        slippage_model_params_json=dict(parent_manifest.slippage_model_params_json),
        benchmark_config_json=dict(parent_manifest.benchmark_config_json),
        resolved_config_json=resolved_config,
        resolved_config_uri=f"memory://runs/{run_id}/resolved_config.json",
        benchmark_config_uri=f"memory://runs/{run_id}/benchmark_config.json",
        run_manifest_uri=f"memory://runs/{run_id}/manifest.json",
        seed=parent_manifest.seed,
    )
    single_run_result = SingleRunOrchestrator().execute(
        request=single_run_request,
        candles=execution_candles,
        signals=mapped_signals,
        constraints=constraints,
        validation_split=execution_validation_split,
    )
    run_repository.save_single_run_result(single_run_result)
    execution = single_run_result.execution
    return ExecutionVerificationResult(
        run_id=run_id,
        parent_run_id=request.parent_run_id,
        stable_candidate_id=request.stable_candidate_id,
        strategy_timeframe=strategy_timeframe,
        execution_timeframe=execution_timeframe,
        signal_count=len(mapped_signals),
        order_count=len(execution.orders),
        fill_count=len(execution.fills),
        warning_count=len(execution.warnings),
        trade_count=single_run_result.metrics.trade_count,
        metrics=single_run_result.metrics,
        single_run_result=single_run_result,
    )


def is_execution_verification_manifest(manifest: RunManifest) -> bool:
    return manifest.resolved_config_json.get("run_type") == EXECUTION_VERIFICATION_RUN_TYPE


def _build_execution_verification_run_id(*, parent_run_id: str, execution_timeframe: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    compact_timeframe = execution_timeframe.replace("/", "")
    return f"ev-{parent_run_id}-exec{compact_timeframe}-{timestamp}"


def _build_resolved_config(
    *,
    run_id: str,
    parent_manifest: RunManifest,
    execution_snapshot: DatasetSnapshot,
    stable_candidate_id: str,
    strategy_timeframe: str,
    execution_timeframe: str,
    signal_count: int,
    strategy_params: dict[str, object],
    signal_filter_set: dict[str, object] | None,
    run_type: str,
    source_run_id: str | None,
) -> dict[str, object]:
    parent_config = dict(parent_manifest.resolved_config_json)
    execution_verification = {
        "parent_run_id": parent_manifest.run_id,
        "stable_candidate_id": stable_candidate_id,
        "strategy_timeframe": strategy_timeframe,
        "execution_timeframe": execution_timeframe,
        "execution_model_version": EXECUTION_VERIFICATION_MODEL_VERSION,
        "signal_count": signal_count,
    }
    if signal_filter_set is not None:
        execution_verification["signal_filter_set"] = signal_filter_set
    return {
        **parent_config,
        "run_id": run_id,
        "dataset_snapshot_id": execution_snapshot.dataset_snapshot_id,
        "symbol": execution_snapshot.symbol,
        "timeframe": execution_timeframe,
        "run_type": run_type,
        "parent_run_id": parent_manifest.run_id,
        "source_run_id": source_run_id or parent_manifest.run_id,
        "stable_candidate_id": stable_candidate_id,
        "strategy_timeframe": strategy_timeframe,
        "execution_timeframe": execution_timeframe,
        "execution_model_version": EXECUTION_VERIFICATION_MODEL_VERSION,
        "strategy_params": strategy_params,
        "execution_verification": execution_verification,
        "source": {
            "type": "stable_candidate",
            "id": stable_candidate_id,
        },
    }


def _build_execution_validation_split(
    *,
    parent_run_id: str,
    parent_manifest: RunManifest,
    execution_snapshot: DatasetSnapshot,
    execution_timeframe: str,
    run_repository: RunRepository,
) -> ValidationSplit | None:
    if parent_manifest.validation_split_id in {"", "validation:none"}:
        return None

    parent_summary = run_repository.load_validation_summary(parent_run_id)
    if parent_summary is None:
        return None

    is_segment = _require_dict(parent_summary.get("is_segment"), "validation_summary.is_segment")
    oos_segment = _require_dict(parent_summary.get("oos_segment"), "validation_summary.oos_segment")
    is_start = _require_datetime(is_segment.get("analysis_start"), "validation_summary.is_segment.analysis_start")
    oos_start = _require_datetime(oos_segment.get("analysis_start"), "validation_summary.oos_segment.analysis_start")
    oos_end = execution_snapshot.time_range_end + _timeframe_delta(execution_timeframe)
    return ValidationSplit(
        validation_split_id=f"{parent_manifest.validation_split_id}:exec-{execution_timeframe}",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id=execution_snapshot.dataset_snapshot_id,
        warmup_bars=0,
        is_start=is_start,
        is_end=oos_start,
        oos_start=oos_start,
        oos_end=oos_end,
    )


def _map_signals_to_execution_timeline(
    signals: list[SignalIntent],
    execution_candles: list[CanonicalCandle],
) -> list[SignalIntent]:
    sorted_execution_candles = sorted(execution_candles, key=lambda candle: candle.timestamp)
    mapped: list[SignalIntent] = []
    for signal in signals:
        execution_candle = next((candle for candle in sorted_execution_candles if candle.timestamp > signal.timestamp), None)
        if execution_candle is None:
            continue
        mapped.append(
            SignalIntent(
                signal_id=signal.signal_id,
                run_id=signal.run_id,
                timestamp=execution_candle.timestamp,
                symbol=signal.symbol,
                action=signal.action,
                side=signal.side,
                qty_policy_ref=signal.qty_policy_ref,
                reason_code=signal.reason_code,
                signal_score=signal.signal_score,
                meta_json={
                    **signal.meta_json,
                    "strategy_signal_timestamp": signal.timestamp.isoformat(),
                    "execution_signal_timestamp": execution_candle.timestamp.isoformat(),
                },
            )
        )
    return mapped


def _validate_execution_coverage(
    *,
    strategy_candles: list[CanonicalCandle],
    execution_candles: list[CanonicalCandle],
) -> None:
    if not strategy_candles:
        raise ValueError("strategy dataset contains no candles")
    if not execution_candles:
        raise ValueError("execution dataset contains no candles")
    strategy_start = strategy_candles[0].timestamp
    strategy_end = strategy_candles[-1].timestamp
    execution_start = execution_candles[0].timestamp
    execution_end = execution_candles[-1].timestamp
    if execution_start > strategy_start:
        raise ValueError(
            "execution dataset does not cover parent run start "
            f"(parent_start={strategy_start.isoformat()}, execution_start={execution_start.isoformat()})"
        )
    if execution_end <= strategy_end:
        raise ValueError(
            "execution dataset does not cover the next executable bar after parent run end "
            f"(parent_end={strategy_end.isoformat()}, execution_end={execution_end.isoformat()})"
        )


def _load_candles(*, snapshot_id: str, dataset_repository: DatasetRepository) -> list[CanonicalCandle]:
    base_dir = getattr(dataset_repository, "base_dir", None)
    if base_dir is None:
        raise ValueError("execution verification requires a file-backed dataset repository")
    path = Path(base_dir) / "datasets" / snapshot_id / "canonical_candles.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            CanonicalCandle(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                symbol=row["symbol"],
                exchange=row["exchange"],
                market_type=MarketType(row["market_type"]),
                timeframe=row["timeframe"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                price_type=PriceType(row.get("price_type", PriceType.LAST.value)),
                data_source=row.get("data_source", "unknown"),
            )
            for row in reader
        ]


def _execution_constraints_from_config(payload: dict[str, object]) -> ExecutionConstraints:
    return ExecutionConstraints(
        initial_cash=float(payload.get("initial_cash", 10_000.0)),
        leverage=float(payload.get("leverage", 1.0)),
        fee_rate=float(payload.get("fee_rate", 0.0)),
        slippage_bps=float(payload.get("slippage_bps", 0.0)),
        min_notional=float(payload.get("min_notional", 0.0)),
        qty_by_policy=_float_dict(payload.get("qty_by_policy")),
        cash_allocation_pct_by_policy=_float_dict(payload.get("cash_allocation_pct_by_policy")),
        risk_pct_per_trade_by_policy=_float_dict(payload.get("risk_pct_per_trade_by_policy")),
        max_equity_drawdown_pct=_optional_float(payload.get("max_equity_drawdown_pct")),
        cooldown_after_consecutive_stop_losses=_optional_int(payload.get("cooldown_after_consecutive_stop_losses")),
        cooldown_bars=_optional_int(payload.get("cooldown_bars")),
        cooldown_only_short_holding_bars=_optional_int(payload.get("cooldown_only_short_holding_bars")),
    )


def _require_dict(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"parent run missing {field_name}")
    return dict(value)


def _require_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    raise ValueError(f"parent run missing {field_name}")


def _timeframe_delta(timeframe: str) -> timedelta:
    normalized = timeframe.strip().lower()
    if normalized.endswith("m"):
        return timedelta(minutes=int(normalized[:-1]))
    if normalized.endswith("h"):
        return timedelta(hours=int(normalized[:-1]))
    if normalized.endswith("d"):
        return timedelta(days=int(normalized[:-1]))
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _float_dict(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {str(key): float(inner) for key, inner in value.items()}


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
