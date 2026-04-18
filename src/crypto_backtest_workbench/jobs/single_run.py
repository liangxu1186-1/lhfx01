"""Single-run orchestration helpers for Phase 1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from crypto_backtest_workbench.domain.models import (
    BacktestRun,
    CanonicalCandle,
    FailureCode,
    RunManifest,
    SignalIntent,
    TaskStatus,
)
from crypto_backtest_workbench.engine.analytics.metrics import RunMetrics, compute_run_metrics
from crypto_backtest_workbench.engine.execution.simulator import (
    ExecutionConstraints,
    ExecutionResult,
    simulate_signals,
)


@dataclass(slots=True)
class SingleRunRequest:
    run_id: str
    strategy_name: str
    strategy_version: str
    dataset_snapshot_id: str
    feature_artifact_id: str
    validation_split_id: str
    execution_policy_id: str
    metric_policy_id: str
    engine_version: str
    fee_model_version: str
    slippage_model_version: str
    fee_model_params_json: dict[str, object]
    slippage_model_params_json: dict[str, object]
    benchmark_config_json: dict[str, object]
    resolved_config_json: dict[str, object]
    resolved_config_uri: str
    benchmark_config_uri: str
    run_manifest_uri: str
    seed: int | None = None


@dataclass(slots=True)
class SingleRunResult:
    manifest: RunManifest
    run: BacktestRun
    execution: ExecutionResult
    metrics: RunMetrics


class SingleRunOrchestrator:
    """Build manifest, simulate execution and assemble a BacktestRun."""

    def execute(
        self,
        *,
        request: SingleRunRequest,
        candles: list[CanonicalCandle],
        signals: list[SignalIntent],
        constraints: ExecutionConstraints,
    ) -> SingleRunResult:
        manifest = RunManifest(
            run_id=request.run_id,
            dataset_snapshot_id=request.dataset_snapshot_id,
            strategy_version=request.strategy_version,
            engine_version=request.engine_version,
            execution_policy_id=request.execution_policy_id,
            metric_policy_id=request.metric_policy_id,
            feature_artifact_id=request.feature_artifact_id,
            validation_split_id=request.validation_split_id,
            fee_model_version=request.fee_model_version,
            slippage_model_version=request.slippage_model_version,
            fee_model_params_json=request.fee_model_params_json,
            slippage_model_params_json=request.slippage_model_params_json,
            benchmark_config_json=request.benchmark_config_json,
            resolved_config_json=request.resolved_config_json,
            seed=request.seed,
        )
        manifest.validate_required_fields()

        execution = simulate_signals(candles=candles, signals=signals, constraints=constraints)
        metrics = compute_run_metrics(
            initial_equity=constraints.initial_cash,
            final_equity=execution.account.equity,
            trades=execution.trades,
        )
        run = BacktestRun(
            run_id=request.run_id,
            strategy_name=request.strategy_name,
            strategy_version=request.strategy_version,
            dataset_snapshot_id=request.dataset_snapshot_id,
            execution_policy_id=request.execution_policy_id,
            metric_policy_id=request.metric_policy_id,
            feature_artifact_id=request.feature_artifact_id,
            engine_version=request.engine_version,
            fee_model_version=request.fee_model_version,
            slippage_model_version=request.slippage_model_version,
            fee_model_params_json=request.fee_model_params_json,
            slippage_model_params_json=request.slippage_model_params_json,
            validation_split_id=request.validation_split_id,
            config_hash=_config_hash(request.resolved_config_json),
            resolved_config_uri=request.resolved_config_uri,
            benchmark_config_uri=request.benchmark_config_uri,
            seed=request.seed,
            run_manifest_uri=request.run_manifest_uri,
            status=TaskStatus.SUCCESS,
        )
        return SingleRunResult(
            manifest=manifest,
            run=run,
            execution=execution,
            metrics=metrics,
        )

    def fail_run(
        self,
        *,
        request: SingleRunRequest,
        failure_code: FailureCode,
        failure_stage: str,
        failure_message: str,
    ) -> BacktestRun:
        return BacktestRun(
            run_id=request.run_id,
            strategy_name=request.strategy_name,
            strategy_version=request.strategy_version,
            dataset_snapshot_id=request.dataset_snapshot_id,
            execution_policy_id=request.execution_policy_id,
            metric_policy_id=request.metric_policy_id,
            feature_artifact_id=request.feature_artifact_id,
            engine_version=request.engine_version,
            fee_model_version=request.fee_model_version,
            slippage_model_version=request.slippage_model_version,
            fee_model_params_json=request.fee_model_params_json,
            slippage_model_params_json=request.slippage_model_params_json,
            validation_split_id=request.validation_split_id,
            config_hash=_config_hash(request.resolved_config_json),
            resolved_config_uri=request.resolved_config_uri,
            benchmark_config_uri=request.benchmark_config_uri,
            seed=request.seed,
            run_manifest_uri=request.run_manifest_uri,
            status=TaskStatus.FAILED,
            failure_code=failure_code,
            failure_stage=failure_stage,
            failure_message=failure_message,
        )


def _config_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
