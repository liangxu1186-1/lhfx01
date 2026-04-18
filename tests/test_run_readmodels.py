from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.readmodels import (
    build_equity_chart_rows,
    build_trade_rows,
    build_warning_rows,
    list_run_summary_views,
    load_run_detail_view,
)
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


def test_run_readmodels_build_summary_and_detail(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))

    summaries = list_run_summary_views(repository)

    assert [summary.run_id for summary in summaries] == ["run-002", "run-001"]
    assert summaries[0].strategy_name == "manual-signals"
    assert summaries[0].trade_count == 1
    assert summaries[0].benchmark_return is not None

    detail = load_run_detail_view(repository, "run-001")
    equity_rows = build_equity_chart_rows(detail)
    trade_rows = build_trade_rows(detail)
    warning_rows = build_warning_rows(detail)

    assert detail.run.run_id == "run-001"
    assert len(equity_rows) == len(detail.execution.equity_curve)
    assert equity_rows[0]["strategy_equity"] == detail.execution.equity_curve[0].equity
    assert equity_rows[0]["benchmark_equity"] is not None
    assert trade_rows[0]["trade_id"] == detail.execution.trades[0].trade_id
    assert warning_rows[0]["warning_code"] == detail.execution.warnings[0].warning_code


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
