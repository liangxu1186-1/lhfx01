from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
        validation_split=ValidationSplit(
            validation_split_id="split-001",
            target_type=ValidationTargetType.DATASET_SNAPSHOT,
            target_id="snapshot-001",
            warmup_bars=0,
            is_start=candles[0].timestamp,
            is_end=candles[4].timestamp,
            oos_start=candles[4].timestamp,
            oos_end=candles[4].timestamp + timedelta(hours=1),
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
    assert paths["validation_summary"].exists()

    loaded_manifest = repository.load_manifest("run-001")
    loaded_run = repository.load_run("run-001")
    loaded_execution = repository.load_execution("run-001")
    loaded_metrics = repository.load_metrics("run-001")
    loaded_benchmark = repository.load_benchmark("run-001")
    loaded_benchmark_result = repository.load_benchmark_result("run-001")
    loaded_validation_summary = repository.load_validation_summary("run-001")

    assert loaded_manifest == result.manifest
    assert loaded_run == result.run
    assert loaded_execution == result.execution
    assert loaded_metrics == result.metrics
    assert loaded_benchmark == result.benchmark_output
    assert loaded_benchmark_result == result.benchmark_output.result
    assert loaded_validation_summary == result.validation_summary
    assert loaded_execution.trades[0].trade_id == result.execution.trades[0].trade_id
    assert repository.load_max_drawdown("run-001") == result.metrics.max_drawdown


def test_file_run_repository_returns_none_when_benchmark_missing(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)

    assert repository.load_benchmark("missing-run") is None
    assert repository.load_benchmark_result("missing-run") is None


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


def test_file_run_repository_loads_legacy_trades_without_planned_sltp(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    result = _build_single_run_result(run_id="run-legacy")
    repository.save_single_run_result(result)
    trades_path = tmp_path / "runs" / "run-legacy" / "execution" / "trades.csv"
    rows = trades_path.read_text(encoding="utf-8").splitlines()
    header = rows[0].split(",")
    stop_index = header.index("planned_stop_loss_price")
    tp_index = header.index("planned_take_profit_price")
    keep_indexes = [index for index in range(len(header)) if index not in {stop_index, tp_index}]
    legacy_rows = []
    for row in rows:
        parts = row.split(",")
        legacy_rows.append(",".join(parts[index] for index in keep_indexes))
    trades_path.write_text("\n".join(legacy_rows), encoding="utf-8")

    loaded = repository.load_execution("run-legacy")

    assert loaded.trades[0].planned_stop_loss_price is None
    assert loaded.trades[0].planned_take_profit_price is None


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
