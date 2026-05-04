"""Task-backed parameter experiment workflow for EMA strategy."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product

from crypto_backtest_workbench.app.workflows.run_backtest import RunBacktestWorkflowRequest
from crypto_backtest_workbench.app.workflows.run_backtest_task import run_backtest_task_workflow
from crypto_backtest_workbench.domain.models import (
    FailureCode,
    ParameterExperiment,
    SearchType,
    SeedPolicy,
    TaskStatus,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.jobs.task_models import TaskRecord
from crypto_backtest_workbench.storage.repositories import (
    DatasetRepository,
    FeatureRepository,
    ParameterExperimentRepository,
    RunRepository,
    TaskRepository,
)


DEFAULT_BENCHMARK_POLICY_VERSION = "buy_and_hold_v1"
DEFAULT_BASE_CONFIG_URI = "memory://parameter-experiments/base-config.json"
DEFAULT_BENCHMARK_CONFIG_URI = "memory://parameter-experiments/benchmark-config.json"


@dataclass(slots=True)
class ParameterExperimentTaskRequest:
    experiment_id: str
    snapshot: object
    search_type: SearchType
    qty_policy_ref: str
    qty: float | None
    initial_cash: float
    leverage_candidates: tuple[float, ...]
    fee_rate: float
    slippage_bps: float
    min_notional: float
    strategy_name: str = "ema_crossover"
    strategy_version: str = "v1"
    fast_periods: tuple[int, ...] = ()
    slow_periods: tuple[int, ...] = ()
    trend_fast_periods: tuple[int, ...] = ()
    trend_slow_periods: tuple[int, ...] = ()
    atr_entry_tolerances: tuple[float, ...] = ()
    atr_stop_mults: tuple[float, ...] = ()
    risk_reward_ratios: tuple[float, ...] = ()
    entry_ema_period: int = 21
    atr_period: int = 14
    min_atr_pct_of_price: float = 0.002
    min_stop_pct: float = 0.003
    cash_allocation_pct: float | None = None
    risk_pct_per_trade: float | None = None
    cash_allocation_pct_candidates: tuple[float, ...] = ()
    risk_pct_per_trade_candidates: tuple[float, ...] = ()
    signal_filter_sets: tuple[dict[str, object], ...] = ()
    benchmark_enabled: bool = True
    max_samples: int | None = None
    seed: int | None = None
    validation_split: object | None = None


@dataclass(slots=True)
class ParameterExperimentTaskWorkflowResult:
    task: TaskRecord
    experiment: ParameterExperiment
    run_ids: list[str]
    child_task_ids: list[str]


def build_parameter_experiment_task(
    request: ParameterExperimentTaskRequest,
) -> tuple[TaskRecord, ParameterExperiment, list[dict[str, object]]]:
    _validate_parameter_experiment_request(request)
    combinations = _build_parameter_combinations(request)
    task = TaskRecord(
        task_id=f"parameter-experiment:{request.experiment_id}",
        task_kind="parameter_experiment",
        status=TaskStatus.PENDING,
    )
    search_space = {
        "strategy_name": request.strategy_name,
        "strategy_version": request.strategy_version,
        "leverage_candidates": list(request.leverage_candidates),
        "cash_allocation_pct_candidates": list(_cash_allocation_candidates(request)),
        "risk_pct_per_trade_candidates": list(_risk_pct_candidates(request)),
        "combination_count": len(combinations),
        "max_samples": request.max_samples,
    }
    search_space.update(_request_search_space(request))
    experiment = ParameterExperiment(
        experiment_id=request.experiment_id,
        strategy_name=request.strategy_name,
        dataset_bundle_id=str(getattr(request.snapshot, "dataset_snapshot_id", "")),
        validation_split_id=(
            getattr(request.validation_split, "validation_split_id", "validation:none")
            if request.validation_split is not None
            else "validation:none"
        ),
        metric_policy_id="metrics_daily_365_v1",
        benchmark_policy_version=DEFAULT_BENCHMARK_POLICY_VERSION,
        benchmark_config_uri=DEFAULT_BENCHMARK_CONFIG_URI,
        search_type=request.search_type,
        search_space_json=search_space,
        base_config_uri=DEFAULT_BASE_CONFIG_URI,
        seed_policy=SeedPolicy.FIXED if request.seed is not None else SeedPolicy.GLOBAL_RANDOM,
        seed=request.seed,
    )
    return task, experiment, combinations


def run_parameter_experiment_task_workflow(
    *,
    request: ParameterExperimentTaskRequest,
    task_repository: TaskRepository,
    experiment_repository: ParameterExperimentRepository,
    dataset_repository: DatasetRepository,
    feature_repository: FeatureRepository,
    run_repository: RunRepository,
) -> ParameterExperimentTaskWorkflowResult:
    task, experiment, combinations = build_parameter_experiment_task(request)
    task_repository.save_task(task)
    experiment_repository.save_experiment(experiment)

    running_task = _transition_task(task, status=TaskStatus.RUNNING)
    task_repository.save_task(running_task)

    run_ids: list[str] = []
    child_task_ids: list[str] = []
    failed_child_task_ids: list[str] = []
    for index, params in enumerate(combinations, start=1):
        run_id = _experiment_run_id(
            experiment_id=request.experiment_id,
            index=index,
            params=params,
        )
        run_ids.append(run_id)
        child_result = run_backtest_task_workflow(
            runner=LocalTaskRunner(),
            dataset_repository=dataset_repository,
            feature_repository=feature_repository,
            run_repository=run_repository,
            request=RunBacktestWorkflowRequest(
                run_id=run_id,
                snapshot=request.snapshot,
                strategy_params=_strategy_params_for_combination(request=request, params=params),
                constraints=ExecutionConstraints(
                    initial_cash=request.initial_cash,
                    leverage=float(params["leverage"]),
                    fee_rate=request.fee_rate,
                    slippage_bps=request.slippage_bps,
                    min_notional=request.min_notional,
                    qty_by_policy={request.qty_policy_ref: request.qty} if request.qty is not None else {},
                    cash_allocation_pct_by_policy=(
                        {request.qty_policy_ref: float(params["cash_allocation_pct"])}
                        if params.get("cash_allocation_pct") is not None
                        else {}
                    ),
                    risk_pct_per_trade_by_policy=(
                        {request.qty_policy_ref: float(params["risk_pct_per_trade"])}
                        if params.get("risk_pct_per_trade") is not None
                        else {}
                    ),
                ),
                validation_split=request.validation_split,
                enable_buy_and_hold_benchmark=request.benchmark_enabled,
                seed=request.seed,
            ),
        )
        child_task_ids.append(child_result.task.task_id)
        task_repository.save_task(child_result.task)
        if child_result.output is None or child_result.task.status is TaskStatus.FAILED:
            failed_child_task_ids.append(child_result.task.task_id)

        experiment_repository.save_execution_index(
            request.experiment_id,
            {
                "experiment_id": request.experiment_id,
                "task_id": running_task.task_id,
                "status": TaskStatus.RUNNING.value,
                "run_ids": run_ids,
                "child_task_ids": child_task_ids,
                "failed_child_task_ids": failed_child_task_ids,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    if failed_child_task_ids:
        final_task = _transition_task(
            running_task,
            status=TaskStatus.FAILED,
            failure_code=FailureCode.ENGINE_RUNTIME_ERROR,
            failure_stage="parameter_experiment_task_workflow",
            failure_message=f"{len(failed_child_task_ids)} child run task(s) failed",
        )
    else:
        final_task = _transition_task(
            running_task,
            status=TaskStatus.SUCCESS,
        )
    task_repository.save_task(final_task)
    experiment_repository.save_execution_index(
        request.experiment_id,
        {
            "experiment_id": request.experiment_id,
            "task_id": final_task.task_id,
            "status": final_task.status.value,
            "run_ids": run_ids,
            "child_task_ids": child_task_ids,
            "failed_child_task_ids": failed_child_task_ids,
            "updated_at": final_task.updated_at.isoformat(),
        },
    )
    return ParameterExperimentTaskWorkflowResult(
        task=final_task,
        experiment=experiment,
        run_ids=run_ids,
        child_task_ids=child_task_ids,
    )


def _build_parameter_combinations(request: ParameterExperimentTaskRequest) -> list[dict[str, object]]:
    cash_candidates = _cash_allocation_candidates(request) or (None,)
    risk_candidates = _risk_pct_candidates(request) or (None,)
    if request.strategy_name == "ema_pullback_atr_v2":
        filter_sets = request.signal_filter_sets or (None,)
        combinations = [
            {
                "trend_fast_period": trend_fast_period,
                "trend_slow_period": trend_slow_period,
                "entry_ema_period": request.entry_ema_period,
                "atr_period": request.atr_period,
                "atr_entry_tolerance": atr_entry_tolerance,
                "atr_stop_mult": atr_stop_mult,
                "risk_reward_ratio": risk_reward_ratio,
                "leverage": leverage,
                "cash_allocation_pct": cash_allocation_pct,
                "risk_pct_per_trade": risk_pct_per_trade,
                "signal_filter_set": signal_filter_set,
            }
            for trend_fast_period, trend_slow_period, atr_entry_tolerance, atr_stop_mult, risk_reward_ratio, leverage, cash_allocation_pct, risk_pct_per_trade, signal_filter_set in product(
                request.trend_fast_periods,
                request.trend_slow_periods,
                request.atr_entry_tolerances,
                request.atr_stop_mults,
                request.risk_reward_ratios,
                request.leverage_candidates,
                cash_candidates,
                risk_candidates,
                filter_sets,
            )
        ]
    else:
        combinations = [
            {
                "fast_period": fast_period,
                "slow_period": slow_period,
                "leverage": leverage,
                "cash_allocation_pct": cash_allocation_pct,
                "risk_pct_per_trade": risk_pct_per_trade,
            }
            for fast_period, slow_period, leverage, cash_allocation_pct, risk_pct_per_trade in product(
                request.fast_periods,
                request.slow_periods,
                request.leverage_candidates,
                cash_candidates,
                risk_candidates,
            )
        ]
    if not combinations:
        raise ValueError("Parameter experiment requires at least one parameter combination")

    if request.search_type is SearchType.GRID:
        return combinations

    sample_size = request.max_samples or len(combinations)
    if sample_size <= 0:
        raise ValueError("max_samples must be positive")
    rng = random.Random(request.seed)
    sample_size = min(sample_size, len(combinations))
    return rng.sample(combinations, sample_size)


def _validate_parameter_experiment_request(request: ParameterExperimentTaskRequest) -> None:
    if not request.experiment_id.strip():
        raise ValueError("experiment_id must not be empty")
    if request.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    _validate_leverage_candidates(request.leverage_candidates)
    if request.fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")
    if request.slippage_bps < 0:
        raise ValueError("slippage_bps must be >= 0")
    if request.min_notional < 0:
        raise ValueError("min_notional must be >= 0")
    if request.qty_policy_ref == "percent_of_cash":
        if not _cash_allocation_candidates(request):
            raise ValueError("cash_allocation_pct must be provided for percent_of_cash")
        if any(value <= 0 or value > 100 for value in _cash_allocation_candidates(request)):
            raise ValueError("cash_allocation_pct must be in (0, 100]")
        if request.qty is not None:
            raise ValueError("qty must be empty for percent_of_cash")
        if _risk_pct_candidates(request):
            raise ValueError("risk_pct_per_trade must be empty for percent_of_cash")
    elif request.qty_policy_ref == "risk_pct_of_equity":
        if not _risk_pct_candidates(request):
            raise ValueError("risk_pct_per_trade must be provided for risk_pct_of_equity")
        if any(value <= 0 or value >= 1 for value in _risk_pct_candidates(request)):
            raise ValueError("risk_pct_per_trade must be in (0, 1)")
        if request.qty is not None:
            raise ValueError("qty must be empty for risk_pct_of_equity")
        if _cash_allocation_candidates(request):
            raise ValueError("cash_allocation_pct must be empty for risk_pct_of_equity")
    elif request.qty_policy_ref == "risk_pct_of_cash_allocation":
        if not _cash_allocation_candidates(request):
            raise ValueError("cash_allocation_pct must be provided for risk_pct_of_cash_allocation")
        if any(value <= 0 or value > 100 for value in _cash_allocation_candidates(request)):
            raise ValueError("cash_allocation_pct must be in (0, 100]")
        if not _risk_pct_candidates(request):
            raise ValueError("risk_pct_per_trade must be provided for risk_pct_of_cash_allocation")
        if any(value <= 0 or value >= 1 for value in _risk_pct_candidates(request)):
            raise ValueError("risk_pct_per_trade must be in (0, 1)")
        if request.qty is not None:
            raise ValueError("qty must be empty for risk_pct_of_cash_allocation")
    else:
        if request.qty is None or request.qty <= 0:
            raise ValueError("qty must be positive")
        if request.cash_allocation_pct is not None:
            raise ValueError("cash_allocation_pct only supports percent_of_cash")
        if request.risk_pct_per_trade is not None:
            raise ValueError("risk_pct_per_trade only supports risk_pct_of_equity")
    if request.search_type is SearchType.GRID and request.max_samples is not None:
        raise ValueError("max_samples is only supported for random search")
    if request.search_type is SearchType.RANDOM and request.max_samples is not None and request.max_samples <= 0:
        raise ValueError("max_samples must be positive")

    if request.strategy_name == "ema_pullback_atr_v2":
        _validate_v2_request(request)
    elif request.strategy_name == "ema_crossover":
        _validate_v1_request(request)
    else:
        raise ValueError(f"Unsupported strategy_name: {request.strategy_name}")


def _validate_v1_request(request: ParameterExperimentTaskRequest) -> None:
    _validate_periods(request.fast_periods, field_name="fast_periods")
    _validate_periods(request.slow_periods, field_name="slow_periods")
    invalid_pairs = [
        (fast_period, slow_period)
        for fast_period, slow_period in product(request.fast_periods, request.slow_periods)
        if fast_period >= slow_period
    ]
    if invalid_pairs:
        examples = ", ".join(f"{fast}/{slow}" for fast, slow in invalid_pairs[:5])
        raise ValueError(f"All parameter combinations must satisfy fast_period < slow_period, invalid pairs: {examples}")


def _validate_v2_request(request: ParameterExperimentTaskRequest) -> None:
    _validate_periods(request.trend_fast_periods, field_name="trend_fast_periods")
    _validate_periods(request.trend_slow_periods, field_name="trend_slow_periods")
    _validate_positive_numbers(request.atr_stop_mults, field_name="atr_stop_mults")
    _validate_positive_numbers(request.risk_reward_ratios, field_name="risk_reward_ratios")
    if not request.atr_entry_tolerances:
        raise ValueError("atr_entry_tolerances must not be empty")
    if any(value < 0 for value in request.atr_entry_tolerances):
        raise ValueError("atr_entry_tolerances must contain only non-negative numbers")
    if len(set(request.atr_entry_tolerances)) != len(request.atr_entry_tolerances):
        raise ValueError("atr_entry_tolerances must not contain duplicate values")
    if request.entry_ema_period <= 0 or request.atr_period <= 0:
        raise ValueError("entry_ema_period and atr_period must be positive")
    if request.min_atr_pct_of_price < 0 or request.min_stop_pct < 0:
        raise ValueError("min ATR/price and min stop pct must be >= 0")
    invalid_pairs = [
        (fast_period, slow_period)
        for fast_period, slow_period in product(request.trend_fast_periods, request.trend_slow_periods)
        if fast_period >= slow_period
    ]
    if invalid_pairs:
        examples = ", ".join(f"{fast}/{slow}" for fast, slow in invalid_pairs[:5])
        raise ValueError(f"All parameter combinations must satisfy trend_fast_period < trend_slow_period, invalid pairs: {examples}")


def _validate_periods(periods: tuple[int, ...], *, field_name: str) -> None:
    if not periods:
        raise ValueError(f"{field_name} must not be empty")
    if any(period <= 0 for period in periods):
        raise ValueError(f"{field_name} must contain only positive integers")
    if len(set(periods)) != len(periods):
        raise ValueError(f"{field_name} must not contain duplicate values")


def _validate_leverage_candidates(leverage_candidates: tuple[float, ...]) -> None:
    if not leverage_candidates:
        raise ValueError("leverage_candidates must not be empty")
    if any(leverage <= 0 for leverage in leverage_candidates):
        raise ValueError("leverage_candidates must contain only positive numbers")
    if len(set(leverage_candidates)) != len(leverage_candidates):
        raise ValueError("leverage_candidates must not contain duplicate values")


def _cash_allocation_candidates(request: ParameterExperimentTaskRequest) -> tuple[float, ...]:
    if request.cash_allocation_pct_candidates:
        return request.cash_allocation_pct_candidates
    return (request.cash_allocation_pct,) if request.cash_allocation_pct is not None else ()


def _risk_pct_candidates(request: ParameterExperimentTaskRequest) -> tuple[float, ...]:
    if request.risk_pct_per_trade_candidates:
        return request.risk_pct_per_trade_candidates
    return (request.risk_pct_per_trade,) if request.risk_pct_per_trade is not None else ()


def _validate_positive_numbers(values: tuple[float, ...], *, field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(value <= 0 for value in values):
        raise ValueError(f"{field_name} must contain only positive numbers")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values")


def _request_search_space(request: ParameterExperimentTaskRequest) -> dict[str, object]:
    if request.strategy_name == "ema_pullback_atr_v2":
        payload = {
            "trend_fast_periods": list(request.trend_fast_periods),
            "trend_slow_periods": list(request.trend_slow_periods),
            "atr_entry_tolerances": list(request.atr_entry_tolerances),
            "atr_stop_mults": list(request.atr_stop_mults),
            "risk_reward_ratios": list(request.risk_reward_ratios),
            "entry_ema_period": request.entry_ema_period,
            "atr_period": request.atr_period,
            "min_atr_pct_of_price": request.min_atr_pct_of_price,
            "min_stop_pct": request.min_stop_pct,
        }
        if _cash_allocation_candidates(request):
            payload["cash_allocation_pct_candidates"] = list(_cash_allocation_candidates(request))
        if _risk_pct_candidates(request):
            payload["risk_pct_per_trade_candidates"] = list(_risk_pct_candidates(request))
        if request.signal_filter_sets:
            payload["signal_filter_sets"] = list(request.signal_filter_sets)
        return payload
    payload = {
        "fast_periods": list(request.fast_periods),
        "slow_periods": list(request.slow_periods),
    }
    if _cash_allocation_candidates(request):
        payload["cash_allocation_pct_candidates"] = list(_cash_allocation_candidates(request))
    if _risk_pct_candidates(request):
        payload["risk_pct_per_trade_candidates"] = list(_risk_pct_candidates(request))
    return payload


def _strategy_params_for_combination(
    *,
    request: ParameterExperimentTaskRequest,
    params: dict[str, object],
) -> dict[str, object]:
    if request.strategy_name == "ema_pullback_atr_v2":
        strategy_params = {
            "strategy_name": "ema_pullback_atr_v2",
            "trend_fast_period": int(params["trend_fast_period"]),
            "trend_slow_period": int(params["trend_slow_period"]),
            "atr_entry_tolerance": float(params["atr_entry_tolerance"]),
            "atr_stop_mult": float(params["atr_stop_mult"]),
            "risk_reward_ratio": float(params["risk_reward_ratio"]),
            "entry_ema_period": request.entry_ema_period,
            "atr_period": request.atr_period,
            "min_atr_pct_of_price": request.min_atr_pct_of_price,
            "min_stop_pct": request.min_stop_pct,
            "qty_policy_ref": request.qty_policy_ref,
        }
        if params.get("cash_allocation_pct") is not None:
            strategy_params["cash_allocation_pct"] = float(params["cash_allocation_pct"])
        if params.get("risk_pct_per_trade") is not None:
            strategy_params["risk_pct_per_trade"] = float(params["risk_pct_per_trade"])
        if params.get("signal_filter_set") is not None:
            signal_filter_set = params["signal_filter_set"]
            if not isinstance(signal_filter_set, dict):
                raise ValueError("signal_filter_set must be an object")
            filters = signal_filter_set.get("filters", [])
            if not isinstance(filters, list):
                raise ValueError("signal_filter_set.filters must be a list")
            strategy_params["signal_filters"] = tuple(filters)
        return strategy_params
    return {
        "strategy_name": "ema_crossover",
        "fast_period": int(params["fast_period"]),
        "slow_period": int(params["slow_period"]),
        "qty_policy_ref": request.qty_policy_ref,
    }


def _experiment_run_id(*, experiment_id: str, params: dict[str, object], index: int) -> str:
    leverage = float(params["leverage"])
    risk_suffix = _risk_suffix(params)
    if "trend_fast_period" in params:
        return (
            f"{experiment_id}-run-{index:03d}"
            f"-tf{int(params['trend_fast_period'])}"
            f"-ts{int(params['trend_slow_period'])}"
            f"-tol{_format_leverage_for_id(float(params['atr_entry_tolerance']))}"
            f"-sl{_format_leverage_for_id(float(params['atr_stop_mult']))}"
            f"-rr{_format_leverage_for_id(float(params['risk_reward_ratio']))}"
            f"-l{_format_leverage_for_id(leverage)}"
            f"{risk_suffix}"
            f"{_filter_suffix(params)}"
        )
    return f"{experiment_id}-run-{index:03d}-f{int(params['fast_period'])}-s{int(params['slow_period'])}-l{_format_leverage_for_id(leverage)}{risk_suffix}"


def _risk_suffix(params: dict[str, object]) -> str:
    parts: list[str] = []
    if params.get("cash_allocation_pct") is not None:
        parts.append(f"cash{_format_leverage_for_id(float(params['cash_allocation_pct']))}")
    if params.get("risk_pct_per_trade") is not None:
        parts.append(f"risk{_format_leverage_for_id(float(params['risk_pct_per_trade']) * 100)}")
    return "" if not parts else "-" + "-".join(parts)


def _filter_suffix(params: dict[str, object]) -> str:
    signal_filter_set = params.get("signal_filter_set")
    if signal_filter_set is None:
        return ""
    if not isinstance(signal_filter_set, dict):
        return "-flt-invalid"
    label = str(signal_filter_set.get("label") or signal_filter_set.get("filter_set_id") or "").strip()
    if label:
        normalized = "".join(char if char.isalnum() else "-" for char in label.lower()).strip("-")
        return f"-flt-{normalized[:24]}"
    digest = hashlib.sha256(json.dumps(signal_filter_set, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:8]
    return f"-flt-{digest}"


def _format_leverage_for_id(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def _transition_task(
    task: TaskRecord,
    *,
    status: TaskStatus,
    failure_code: FailureCode | None = None,
    failure_stage: str | None = None,
    failure_message: str | None = None,
) -> TaskRecord:
    return TaskRecord(
        task_id=task.task_id,
        task_kind=task.task_kind,
        status=status,
        created_at=task.created_at,
        updated_at=datetime.now(UTC),
        failure_code=failure_code,
        failure_stage=failure_stage,
        failure_message=failure_message,
    )
