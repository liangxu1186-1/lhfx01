from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    FeatureSpec,
    MarketType,
    Side,
    SignalAction,
)
from crypto_backtest_workbench.engine.features import FeatureCacheRegistry, FeaturePipeline
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.strategy import EMACrossoverStrategy, StrategyInput
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest
from crypto_backtest_workbench.storage.repositories import FileFeatureRepository


def test_single_run_integration_materializes_features_generates_signals_and_executes(tmp_path) -> None:
    candles = _build_candles([100.0, 98.0, 99.0, 103.0, 104.0, 100.0, 96.0, 95.0])
    repository = FileFeatureRepository(tmp_path)
    pipeline = FeaturePipeline(repository, cache_registry=FeatureCacheRegistry())
    strategy = EMACrossoverStrategy(fast_period=2, slow_period=3)

    artifact = pipeline.materialize(
        dataset_snapshot_id="snapshot-001",
        candles=candles,
        specs=strategy.feature_specs(),
    )
    signals = strategy.generate_signals(
        StrategyInput(
            run_id="run-001",
            symbol="BTC/USDT:USDT",
            timeframe="1h",
            feature_artifact_id=artifact.feature_artifact_id,
            features_uri=artifact.storage_uri,
            config={"qty_policy_ref": "fixed_1"},
        )
    )
    result = SingleRunOrchestrator().execute(
        request=SingleRunRequest(
            run_id="run-001",
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            dataset_snapshot_id="snapshot-001",
            feature_artifact_id=artifact.feature_artifact_id,
            validation_split_id="split-001",
            execution_policy_id="signal_on_bar_close_fill_on_next_bar_open",
            metric_policy_id="metric-v1",
            engine_version="engine-v1",
            fee_model_version="fee-v1",
            slippage_model_version="slippage-v1",
            fee_model_params_json={"rate": 0.001},
            slippage_model_params_json={"bps": 0},
            benchmark_config_json={"benchmark_type": "buy_and_hold"},
            resolved_config_json={"qty_policy_ref": "fixed_1"},
            resolved_config_uri="memory://resolved-config.json",
            benchmark_config_uri="memory://benchmark-config.json",
            run_manifest_uri="memory://run-manifest.json",
        ),
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=2.0,
            fee_rate=0.001,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    assert artifact.storage_uri.endswith("feature_rows.csv")
    assert len(signals) == 2
    assert signals[0].action is SignalAction.OPEN
    assert signals[0].side is Side.LONG
    assert signals[1].action is SignalAction.REVERSE
    assert signals[1].side is Side.SHORT
    assert result.metrics.trade_count == 1
    assert len(result.execution.trades) == 2
    assert result.execution.trades[0].exit_time is not None
    assert result.execution.trades[1].side is Side.SHORT
    assert result.run.status.value == "success"


def _build_candles(close_prices: list[float]) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, close_price in enumerate(close_prices):
        timestamp = start + timedelta(hours=index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=close_price,
                high=close_price + 1,
                low=close_price - 1,
                close=close_price,
                volume=100.0,
            )
        )
    return candles
