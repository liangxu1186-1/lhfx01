"""Application-layer backtest workflow assembly for Phase 1."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    DatasetSnapshot,
    FeatureArtifact,
    MarketType,
    PriceType,
    SignalIntent,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.features import FeaturePipeline
from crypto_backtest_workbench.engine.strategy import EMACrossoverStrategy, EMAPullbackATRStrategy, StrategyDefinition, StrategyInput
from crypto_backtest_workbench.jobs import (
    SingleRunOrchestrator,
    SingleRunRequest,
    SingleRunResult,
)
from crypto_backtest_workbench.storage.repositories import DatasetRepository, FeatureRepository


DEFAULT_EXECUTION_POLICY_ID = "signal_on_bar_close_fill_on_next_bar_open"
DEFAULT_METRIC_POLICY_ID = "metrics_daily_365_v1"
DEFAULT_ENGINE_VERSION = "engine-v1"
DEFAULT_FEE_MODEL_VERSION = "fee-flat-rate-v1"
DEFAULT_SLIPPAGE_MODEL_VERSION = "slippage-fixed-bps-v1"
DEFAULT_VALIDATION_SPLIT_ID = "validation:none"

_EMA_STRATEGY_ALLOWED_FIELDS = {
    "fast_period",
    "slow_period",
    "input_price_field",
    "qty_policy_ref",
    "feature_version",
    "name",
    "version",
}
_V2_STRATEGY_ALLOWED_FIELDS = {
    "trend_fast_period",
    "trend_slow_period",
    "atr_entry_tolerance",
    "atr_stop_mult",
    "risk_reward_ratio",
    "entry_ema_period",
    "atr_period",
    "min_atr_pct_of_price",
    "min_stop_pct",
    "qty_policy_ref",
    "cash_allocation_pct",
    "risk_pct_per_trade",
    "input_price_field",
    "signal_filters",
    "name",
    "version",
}


@dataclass(slots=True)
class RunBacktestWorkflowRequest:
    run_id: str
    snapshot: DatasetSnapshot
    strategy_params: dict[str, object]
    constraints: ExecutionConstraints
    validation_split: ValidationSplit | None = None
    enable_buy_and_hold_benchmark: bool = False
    execution_policy_id: str = DEFAULT_EXECUTION_POLICY_ID
    metric_policy_id: str = DEFAULT_METRIC_POLICY_ID
    engine_version: str = DEFAULT_ENGINE_VERSION
    fee_model_version: str = DEFAULT_FEE_MODEL_VERSION
    slippage_model_version: str = DEFAULT_SLIPPAGE_MODEL_VERSION
    seed: int | None = None


@dataclass(slots=True)
class RunBacktestWorkflowResult:
    candles: list[CanonicalCandle]
    strategy: StrategyDefinition
    feature_artifact: FeatureArtifact
    signals: list[SignalIntent]
    single_run_result: SingleRunResult


def run_backtest_workflow(
    *,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    request: RunBacktestWorkflowRequest,
    feature_pipeline: FeaturePipeline | None = None,
    orchestrator: SingleRunOrchestrator | None = None,
) -> RunBacktestWorkflowResult:
    """Resolve a dataset snapshot into a single executable EMA backtest."""

    _validate_validation_split(snapshot=request.snapshot, validation_split=request.validation_split)
    candles = _load_candles(snapshot=request.snapshot, dataset_repository=dataset_repository)
    strategy = build_strategy(request.strategy_params)

    pipeline = feature_pipeline or FeaturePipeline(feature_repository)
    artifact = pipeline.materialize(
        dataset_snapshot_id=request.snapshot.dataset_snapshot_id,
        candles=candles,
        specs=strategy.feature_specs(),
        depends_on=(request.snapshot.dataset_snapshot_id,),
    )
    signals = strategy.generate_signals(
        StrategyInput(
            run_id=request.run_id,
            symbol=request.snapshot.symbol,
            timeframe=request.snapshot.timeframe,
            feature_artifact_id=artifact.feature_artifact_id,
            features_uri=artifact.storage_uri,
            config={"qty_policy_ref": getattr(strategy, "qty_policy_ref", "fixed_notional_v1")},
        )
    )

    resolved_config = _build_resolved_config(request=request, strategy=strategy, artifact=artifact)
    single_run_request = SingleRunRequest(
        run_id=request.run_id,
        strategy_name=strategy.name,
        strategy_version=strategy.version,
        dataset_snapshot_id=request.snapshot.dataset_snapshot_id,
        feature_artifact_id=artifact.feature_artifact_id,
        validation_split_id=_validation_split_id(request.validation_split),
        execution_policy_id=request.execution_policy_id,
        metric_policy_id=request.metric_policy_id,
        engine_version=request.engine_version,
        fee_model_version=request.fee_model_version,
        slippage_model_version=request.slippage_model_version,
        fee_model_params_json={"rate": request.constraints.fee_rate},
        slippage_model_params_json={"bps": request.constraints.slippage_bps},
        benchmark_config_json=_benchmark_config_json(request.enable_buy_and_hold_benchmark),
        resolved_config_json=resolved_config,
        resolved_config_uri=f"memory://runs/{request.run_id}/resolved_config.json",
        benchmark_config_uri=f"memory://runs/{request.run_id}/benchmark_config.json",
        run_manifest_uri=f"memory://runs/{request.run_id}/manifest.json",
        seed=request.seed,
    )

    result = (orchestrator or SingleRunOrchestrator()).execute(
        request=single_run_request,
        candles=candles,
        signals=signals,
        constraints=request.constraints,
        validation_split=request.validation_split,
    )
    return RunBacktestWorkflowResult(
        candles=candles,
        strategy=strategy,
        feature_artifact=artifact,
        signals=signals,
        single_run_result=result,
    )


def build_strategy(strategy_params: dict[str, object]) -> StrategyDefinition:
    strategy_name = str(strategy_params.get("strategy_name") or strategy_params.get("name") or "ema_crossover")
    if strategy_name == "ema_crossover":
        return _build_ema_strategy(strategy_params)
    if strategy_name == "ema_pullback_atr_v2":
        return _build_v2_strategy(strategy_params)
    raise ValueError(f"Unsupported strategy_name: {strategy_name}")


def _build_ema_strategy(strategy_params: dict[str, object]) -> EMACrossoverStrategy:
    unknown_keys = sorted(set(strategy_params) - _EMA_STRATEGY_ALLOWED_FIELDS)
    unknown_keys = [key for key in unknown_keys if key != "strategy_name"]
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(f"Unsupported EMA strategy params: {joined}")
    payload = {key: value for key, value in strategy_params.items() if key != "strategy_name"}
    return EMACrossoverStrategy(**payload)


def _build_v2_strategy(strategy_params: dict[str, object]) -> EMAPullbackATRStrategy:
    unknown_keys = sorted(set(strategy_params) - _V2_STRATEGY_ALLOWED_FIELDS - {"strategy_name"})
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(f"Unsupported EMA Pullback ATR v2 strategy params: {joined}")
    payload = {key: value for key, value in strategy_params.items() if key != "strategy_name"}
    payload["name"] = "ema_pullback_atr_v2"
    payload["version"] = "v2"
    return EMAPullbackATRStrategy(**payload)


def _build_resolved_config(
    *,
    request: RunBacktestWorkflowRequest,
    strategy: StrategyDefinition,
    artifact: FeatureArtifact,
) -> dict[str, object]:
    return {
        "run_id": request.run_id,
        "dataset_snapshot_id": request.snapshot.dataset_snapshot_id,
        "symbol": request.snapshot.symbol,
        "timeframe": request.snapshot.timeframe,
        "strategy_name": strategy.name,
        "strategy_version": strategy.version,
        "strategy_params": _strategy_params(strategy),
        "feature_artifact_id": artifact.feature_artifact_id,
        "feature_cache_key": artifact.feature_cache_key,
        "execution_constraints": {
            "initial_cash": request.constraints.initial_cash,
            "leverage": request.constraints.leverage,
            "fee_rate": request.constraints.fee_rate,
            "slippage_bps": request.constraints.slippage_bps,
            "min_notional": request.constraints.min_notional,
            "qty_by_policy": dict(sorted(request.constraints.qty_by_policy.items())),
            "cash_allocation_pct_by_policy": dict(sorted(request.constraints.cash_allocation_pct_by_policy.items())),
            "risk_pct_per_trade_by_policy": dict(sorted(request.constraints.risk_pct_per_trade_by_policy.items())),
            "max_equity_drawdown_pct": request.constraints.max_equity_drawdown_pct,
            "cooldown_after_consecutive_stop_losses": request.constraints.cooldown_after_consecutive_stop_losses,
            "cooldown_bars": request.constraints.cooldown_bars,
            "cooldown_only_short_holding_bars": request.constraints.cooldown_only_short_holding_bars,
        },
        "validation_split_id": _validation_split_id(request.validation_split),
        "benchmark": _benchmark_config_json(request.enable_buy_and_hold_benchmark),
        "seed": request.seed,
    }


def _strategy_params(strategy: StrategyDefinition) -> dict[str, object]:
    if hasattr(strategy, "strategy_params"):
        return dict(sorted(getattr(strategy, "strategy_params")().items()))
    keys = (
        "fast_period",
        "slow_period",
        "input_price_field",
        "qty_policy_ref",
        "feature_version",
        "name",
        "version",
    )
    return {
        key: getattr(strategy, key)
        for key in keys
        if hasattr(strategy, key)
    }


def _benchmark_config_json(enable_buy_and_hold_benchmark: bool) -> dict[str, object]:
    if enable_buy_and_hold_benchmark:
        return {"benchmark_type": "buy_and_hold"}
    return {"benchmark_type": "none"}


def _validation_split_id(validation_split: ValidationSplit | None) -> str:
    if validation_split is None:
        return DEFAULT_VALIDATION_SPLIT_ID
    return validation_split.validation_split_id


def _validate_validation_split(
    *,
    snapshot: DatasetSnapshot,
    validation_split: ValidationSplit | None,
) -> None:
    if validation_split is None:
        return
    if validation_split.target_type is not ValidationTargetType.DATASET_SNAPSHOT:
        raise ValueError("run_backtest_workflow only supports dataset-snapshot validation splits")
    if validation_split.target_id != snapshot.dataset_snapshot_id:
        raise ValueError("validation_split target_id must match the dataset snapshot")


def _load_candles(
    *,
    snapshot: DatasetSnapshot,
    dataset_repository: DatasetRepository,
) -> list[CanonicalCandle]:
    path = _resolve_candles_path(snapshot=snapshot, dataset_repository=dataset_repository)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[CanonicalCandle] = []
        for raw_row in reader:
            rows.append(
                CanonicalCandle(
                    timestamp=datetime.fromisoformat(raw_row["timestamp"]),
                    symbol=raw_row["symbol"],
                    exchange=raw_row["exchange"],
                    market_type=MarketType(raw_row["market_type"]),
                    timeframe=raw_row["timeframe"],
                    open=float(raw_row["open"]),
                    high=float(raw_row["high"]),
                    low=float(raw_row["low"]),
                    close=float(raw_row["close"]),
                    volume=float(raw_row["volume"]),
                    price_type=PriceType(raw_row.get("price_type", PriceType.LAST.value)),
                    data_source=raw_row.get("data_source", snapshot.data_source),
                )
            )
    if not rows:
        raise ValueError(f"Dataset snapshot {snapshot.dataset_snapshot_id} contains no candles")
    return rows


def _resolve_candles_path(
    *,
    snapshot: DatasetSnapshot,
    dataset_repository: DatasetRepository,
) -> Path:
    uri_path = _path_from_storage_uri(snapshot.storage_uri)
    candidates = list(_candidate_paths(uri_path=uri_path, snapshot=snapshot, dataset_repository=dataset_repository))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not resolve candles path for {snapshot.dataset_snapshot_id}: {joined}")


def _candidate_paths(
    *,
    uri_path: Path,
    snapshot: DatasetSnapshot,
    dataset_repository: DatasetRepository,
):
    if uri_path.suffix == ".csv":
        yield uri_path
    else:
        yield uri_path / "canonical_candles.csv"

    base_dir = getattr(dataset_repository, "base_dir", None)
    if base_dir is None:
        return

    base_dir_path = Path(base_dir)
    if not uri_path.is_absolute():
        if uri_path.suffix == ".csv":
            yield base_dir_path / uri_path
        else:
            yield base_dir_path / uri_path / "canonical_candles.csv"
    yield base_dir_path / "datasets" / snapshot.dataset_snapshot_id / "canonical_candles.csv"


def _path_from_storage_uri(storage_uri: str) -> Path:
    if storage_uri.startswith("file://"):
        return Path(storage_uri.removeprefix("file://"))
    return Path(storage_uri)
