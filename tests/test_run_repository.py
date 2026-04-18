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
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest
from crypto_backtest_workbench.storage.repositories import FileRunRepository


def test_file_run_repository_round_trips_single_run_result(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    candles = _build_candles([100.0, 102.0, 105.0, 103.0, 104.0])
    signals = [
        SignalIntent(
            signal_id="signal-open",
            run_id="run-001",
            timestamp=candles[0].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.OPEN,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="open-long",
        ),
        SignalIntent(
            signal_id="signal-close",
            run_id="run-001",
            timestamp=candles[2].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-long",
        ),
        SignalIntent(
            signal_id="signal-warning",
            run_id="run-001",
            timestamp=candles[-1].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-no-next-open",
        ),
    ]
    result = SingleRunOrchestrator().execute(
        request=SingleRunRequest(
            run_id="run-001",
            strategy_name="manual-signals",
            strategy_version="strategy-v1",
            dataset_snapshot_id="snapshot-001",
            feature_artifact_id="feature-001",
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
            seed=7,
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

    paths = repository.save_single_run_result(result)

    assert paths["manifest"].exists()
    assert paths["run"].exists()
    assert paths["metrics"].exists()
    assert paths["execution"]["orders"].exists()
    assert paths["execution"]["fills"].exists()
    assert paths["execution"]["trades"].exists()
    assert paths["execution"]["equity_curve"].exists()
    assert paths["execution"]["warnings"].exists()
    assert paths["execution"]["account"].exists()
    assert paths["benchmark"]["result"].exists()
    assert paths["benchmark"]["equity_points"].exists()
    assert paths["benchmark"]["daily_returns"].exists()

    loaded_manifest = repository.load_manifest("run-001")
    loaded_run = repository.load_run("run-001")
    loaded_execution = repository.load_execution("run-001")
    loaded_metrics = repository.load_metrics("run-001")
    loaded_benchmark = repository.load_benchmark("run-001")

    assert loaded_manifest == result.manifest
    assert loaded_run == result.run
    assert loaded_execution == result.execution
    assert loaded_metrics == result.metrics
    assert loaded_benchmark == result.benchmark_output
    assert loaded_execution.warnings[0].warning_code == "SIGNAL_SKIPPED_NO_NEXT_OPEN"


def test_file_run_repository_returns_none_when_benchmark_missing(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)

    assert repository.load_benchmark("missing-run") is None


def test_file_run_repository_lists_only_persisted_runs(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    result = _build_single_run_result(run_id="run-b")
    repository.save_single_run_result(result)

    orphan_dir = tmp_path / "runs" / "run-orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "manifest.json").write_text("{}", encoding="utf-8")

    second = _build_single_run_result(run_id="run-a")
    repository.save_single_run_result(second)

    assert repository.list_run_ids() == ["run-a", "run-b"]


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


def _build_single_run_result(*, run_id: str):
    candles = _build_candles([100.0, 102.0, 105.0, 103.0, 104.0])
    signals = [
        SignalIntent(
            signal_id=f"{run_id}-signal-open",
            run_id=run_id,
            timestamp=candles[0].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.OPEN,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="open-long",
        ),
        SignalIntent(
            signal_id=f"{run_id}-signal-close",
            run_id=run_id,
            timestamp=candles[2].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-long",
        ),
        SignalIntent(
            signal_id=f"{run_id}-signal-warning",
            run_id=run_id,
            timestamp=candles[-1].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-no-next-open",
        ),
    ]
    return SingleRunOrchestrator().execute(
        request=SingleRunRequest(
            run_id=run_id,
            strategy_name="manual-signals",
            strategy_version="strategy-v1",
            dataset_snapshot_id="snapshot-001",
            feature_artifact_id="feature-001",
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
            seed=7,
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
