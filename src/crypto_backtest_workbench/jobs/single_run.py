"""Single-run orchestration helpers for Phase 1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from crypto_backtest_workbench.domain.models import (
    BacktestRun,
    BenchmarkConfig,
    CanonicalCandle,
    FailureCode,
    RunManifest,
    SignalIntent,
    TaskStatus,
    ValidationSplit,
)
from crypto_backtest_workbench.engine.analytics import BuyAndHoldBenchmarkOutput, compute_buy_and_hold_benchmark
from crypto_backtest_workbench.engine.analytics.metrics import RunMetrics, compute_run_metrics
from crypto_backtest_workbench.engine.execution.simulator import (
    ExecutionConstraints,
    ExecutionResult,
    simulate_signals,
)
from crypto_backtest_workbench.engine.validation import ValidationView, build_validation_view


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
    validation_view: ValidationView | None = None
    validation_summary: dict[str, object] | None = None
    benchmark_output: BuyAndHoldBenchmarkOutput | None = None


class SingleRunOrchestrator:
    """Build manifest, simulate execution and assemble a BacktestRun."""

    def execute(
        self,
        *,
        request: SingleRunRequest,
        candles: list[CanonicalCandle],
        signals: list[SignalIntent],
        constraints: ExecutionConstraints,
        validation_split: ValidationSplit | None = None,
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

        validation_view = None
        execution_candles = candles
        execution_signals = signals
        if validation_split is not None:
            validation_view = build_validation_view(candles=candles, split=validation_split)
            execution_candles = list(validation_view.is_segment.analysis_candles)
            execution_signals = _filter_signals_for_segment(signals, validation_view.is_segment.analysis_candles)

        execution = simulate_signals(
            candles=execution_candles,
            signals=execution_signals,
            constraints=constraints,
        )
        metrics = compute_run_metrics(
            initial_equity=constraints.initial_cash,
            final_equity=execution.account.equity,
            trades=execution.trades,
            equity_curve=execution.equity_curve,
        )
        benchmark_output = _compute_benchmark_output(
            request=request,
            candles=execution_candles,
            initial_equity=constraints.initial_cash,
        )
        validation_summary = _build_validation_summary(
            request=request,
            validation_view=validation_view,
            signals=signals,
            constraints=constraints,
            is_execution=execution,
            is_metrics=metrics,
            is_benchmark=benchmark_output,
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
            validation_view=validation_view,
            validation_summary=validation_summary,
            benchmark_output=benchmark_output,
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


def _filter_signals_for_segment(
    signals: list[SignalIntent],
    analysis_candles: tuple[CanonicalCandle, ...],
) -> list[SignalIntent]:
    allowed_timestamps = {candle.timestamp for candle in analysis_candles}
    return [signal for signal in signals if signal.timestamp in allowed_timestamps]


def _build_validation_summary(
    *,
    request: SingleRunRequest,
    validation_view: ValidationView | None,
    signals: list[SignalIntent],
    constraints: ExecutionConstraints,
    is_execution: ExecutionResult,
    is_metrics: RunMetrics,
    is_benchmark: BuyAndHoldBenchmarkOutput | None,
) -> dict[str, object] | None:
    if validation_view is None:
        return None

    oos_signals = _filter_signals_for_segment(signals, validation_view.oos_segment.analysis_candles)
    oos_execution = simulate_signals(
        candles=list(validation_view.oos_segment.analysis_candles),
        signals=oos_signals,
        constraints=constraints,
    )
    oos_metrics = compute_run_metrics(
        initial_equity=constraints.initial_cash,
        final_equity=oos_execution.account.equity,
        trades=oos_execution.trades,
        equity_curve=oos_execution.equity_curve,
    )
    oos_benchmark = _compute_benchmark_output(
        request=request,
        candles=list(validation_view.oos_segment.analysis_candles),
        initial_equity=constraints.initial_cash,
    )
    return {
        "validation_split_id": request.validation_split_id,
        "is_segment": _segment_summary_payload(
            segment=validation_view.is_segment,
            metrics=is_metrics,
            benchmark_output=is_benchmark,
        ),
        "oos_segment": _segment_summary_payload(
            segment=validation_view.oos_segment,
            metrics=oos_metrics,
            benchmark_output=oos_benchmark,
        ),
    }


def _segment_summary_payload(
    *,
    segment,
    metrics: RunMetrics,
    benchmark_output: BuyAndHoldBenchmarkOutput | None,
) -> dict[str, object]:
    benchmark_return = benchmark_output.result.return_pct if benchmark_output is not None else None
    excess_return = metrics.total_return - benchmark_return if benchmark_return is not None else None
    analysis_start = segment.analysis_candles[0].timestamp if segment.analysis_candles else None
    analysis_end = segment.analysis_candles[-1].timestamp if segment.analysis_candles else None
    return {
        "name": segment.name,
        "warmup_bars": len(segment.warmup_candles),
        "analysis_bar_count": len(segment.analysis_candles),
        "window_bar_count": len(segment.window_candles),
        "warmup_complete": segment.warmup_complete,
        "analysis_start": analysis_start.isoformat() if analysis_start is not None else None,
        "analysis_end": analysis_end.isoformat() if analysis_end is not None else None,
        "metrics": asdict(metrics),
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
    }


def _compute_benchmark_output(
    *,
    request: SingleRunRequest,
    candles: list[CanonicalCandle],
    initial_equity: float,
) -> BuyAndHoldBenchmarkOutput | None:
    benchmark_type = request.benchmark_config_json.get("benchmark_type")
    if benchmark_type != "buy_and_hold" or not candles:
        return None

    config = BenchmarkConfig(benchmark_type="buy_and_hold")
    return compute_buy_and_hold_benchmark(
        run_id=request.run_id,
        candles=candles,
        config=config,
        initial_equity=initial_equity,
        equity_uri=f"memory://benchmarks/{request.run_id}/buy_and_hold/equity.json",
        daily_returns_uri=f"memory://benchmarks/{request.run_id}/buy_and_hold/daily_returns.json",
    )
