from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    MarketType,
    Side,
    SignalAction,
    SignalIntent,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest


def test_single_run_orchestrator_includes_validation_view_and_buy_hold_benchmark() -> None:
    candles = _build_candles([100.0, 101.0, 103.0, 105.0, 107.0, 109.0])
    split = ValidationSplit(
        validation_split_id="split-001",
        target_type=ValidationTargetType.DATASET_SNAPSHOT,
        target_id="snapshot-001",
        warmup_bars=2,
        is_start=candles[2].timestamp,
        is_end=candles[5].timestamp,
        oos_start=candles[5].timestamp,
        oos_end=candles[5].timestamp + timedelta(hours=1),
    )
    signals = [
        _signal("sig-open", candles[2].timestamp, SignalAction.OPEN, Side.LONG),
        _signal("sig-close", candles[3].timestamp, SignalAction.CLOSE, Side.LONG),
    ]

    result = SingleRunOrchestrator().execute(
        request=_request(),
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=2.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
        validation_split=split,
    )

    assert result.validation_view is not None
    assert [c.timestamp for c in result.validation_view.is_segment.analysis_candles] == [
        candles[2].timestamp,
        candles[3].timestamp,
        candles[4].timestamp,
    ]
    assert result.benchmark_output is not None
    assert result.benchmark_output.result.benchmark_type == "buy_and_hold"
    assert result.benchmark_output.result.return_pct == pytest.approx((107.0 - 103.0) / 103.0)
    assert result.metrics.trade_count == 1


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


def _build_candles(close_prices: list[float]) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, close_price in enumerate(close_prices):
        candles.append(
            CanonicalCandle(
                timestamp=start + timedelta(hours=index),
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=close_price,
                high=close_price,
                low=close_price,
                close=close_price,
                volume=10.0,
            )
        )
    return candles


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
