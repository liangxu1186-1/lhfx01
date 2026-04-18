from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    MarketType,
    Side,
    SignalAction,
    SignalIntent,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import (
    LocalTaskRunner,
    PreparedSingleRunExecutor,
    PreparedSingleRunInput,
    SingleRunOrchestrator,
    SingleRunRequest,
    SingleRunTaskPayload,
)


def test_task_runner_can_execute_prepared_single_run_orchestrator() -> None:
    runner = LocalTaskRunner()
    payload = SingleRunTaskPayload(
        run_id="run-001",
        dataset_snapshot_id="snapshot-001",
        feature_artifact_id="feature-001",
        strategy_name="ema_crossover",
        validation_split_id="split-001",
    )
    task = runner.submit_single_run(payload)
    executor = PreparedSingleRunExecutor(
        orchestrator=SingleRunOrchestrator(),
        prepared_inputs={
            "run-001": PreparedSingleRunInput(
                payload=payload,
                request=_request(),
                candles=_candles(),
                signals=[
                    _signal("sig-open", _candles()[0].timestamp, SignalAction.OPEN, Side.LONG),
                    _signal("sig-close", _candles()[1].timestamp, SignalAction.CLOSE, Side.LONG),
                ],
                constraints=ExecutionConstraints(
                    initial_cash=1_000.0,
                    leverage=2.0,
                    fee_rate=0.0,
                    qty_by_policy={"fixed_1": 1.0},
                ),
            )
        },
    )

    output = runner.run_single_run(task.task_id, executor)

    assert output is not None
    assert output.run.run_id == "run-001"
    assert runner.get_task(task.task_id).status.value == "success"


def _request() -> SingleRunRequest:
    return SingleRunRequest(
        run_id="run-001",
        strategy_name="ema_crossover",
        strategy_version="ema-v1",
        dataset_snapshot_id="snapshot-001",
        feature_artifact_id="feature-001",
        validation_split_id="split-001",
        execution_policy_id="signal_on_bar_close_fill_on_next_bar_open",
        metric_policy_id="metric-v1",
        engine_version="engine-v1",
        fee_model_version="fee-v1",
        slippage_model_version="slippage-v1",
        fee_model_params_json={"rate": 0.0},
        slippage_model_params_json={"bps": 0},
        benchmark_config_json={"benchmark_type": "buy_and_hold"},
        resolved_config_json={"qty_policy_ref": "fixed_1"},
        resolved_config_uri="memory://resolved-config.json",
        benchmark_config_uri="memory://benchmark-config.json",
        run_manifest_uri="memory://run-manifest.json",
    )


def _candles() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        CanonicalCandle(
            timestamp=start + timedelta(hours=index),
            symbol="BTC/USDT:USDT",
            exchange="binance",
            market_type=MarketType.LINEAR_USDT_PERPETUAL,
            timeframe="1h",
            open=100.0 + (index * 2),
            high=101.0 + (index * 2),
            low=99.0 + (index * 2),
            close=100.0 + (index * 2),
            volume=10.0,
        )
        for index in range(3)
    ]


def _signal(signal_id: str, timestamp: datetime, action: SignalAction, side: Side) -> SignalIntent:
    return SignalIntent(
        signal_id=signal_id,
        run_id="run-001",
        timestamp=timestamp,
        symbol="BTC/USDT:USDT",
        action=action,
        side=side,
        qty_policy_ref="fixed_1",
        reason_code=signal_id,
    )
