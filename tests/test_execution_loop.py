from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    MarketType,
    PriceType,
    Side,
    SignalAction,
    SignalIntent,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints, simulate_signals
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest


def test_simulate_signals_fills_on_next_bar_open_and_closes_trade() -> None:
    candles = _sample_candles()
    signals = [
        _signal(
            signal_id="sig-open",
            timestamp=candles[0].timestamp,
            action=SignalAction.OPEN,
            side=Side.LONG,
        ),
        _signal(
            signal_id="sig-close",
            timestamp=candles[1].timestamp,
            action=SignalAction.CLOSE,
            side=Side.LONG,
        ),
    ]

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=2.0,
            fee_rate=0.001,
            slippage_bps=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    assert len(result.orders) == 2
    assert len(result.fills) == 2
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == candles[1].timestamp
    assert trade.entry_price == candles[1].open
    assert trade.exit_time == candles[2].timestamp
    assert trade.exit_price == candles[2].open
    assert trade.net_pnl > 0
    assert result.account.equity > 1_000.0


def test_simulate_signals_rejects_order_when_margin_is_insufficient() -> None:
    candles = _sample_candles()
    signals = [
        _signal(
            signal_id="sig-open",
            timestamp=candles[0].timestamp,
            action=SignalAction.OPEN,
            side=Side.LONG,
        )
    ]

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=10.0,
            leverage=1.0,
            fee_rate=0.0,
            min_notional=0.0,
            qty_by_policy={"fixed_1": 100.0},
        ),
    )

    assert len(result.orders) == 1
    assert result.orders[0].status == "rejected"
    assert result.orders[0].reject_reason_code is not None
    assert result.trades == []


def test_simulate_signals_percent_of_cash_uses_dynamic_available_cash() -> None:
    candles = _sample_candles_for_dynamic_sizing()
    signals = [
        _signal(signal_id="sig-open-1", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG),
        _signal(signal_id="sig-close-1", timestamp=candles[1].timestamp, action=SignalAction.CLOSE, side=Side.LONG),
        _signal(signal_id="sig-open-2", timestamp=candles[2].timestamp, action=SignalAction.OPEN, side=Side.LONG),
        _signal(signal_id="sig-close-2", timestamp=candles[3].timestamp, action=SignalAction.CLOSE, side=Side.LONG),
    ]
    for signal in signals:
        signal.qty_policy_ref = "percent_of_cash"

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=2.0,
            fee_rate=0.0,
            cash_allocation_pct_by_policy={"percent_of_cash": 100.0},
        ),
    )

    assert len(result.trades) == 2
    first_trade, second_trade = result.trades
    assert round(first_trade.qty, 6) == 20.0
    assert round(second_trade.qty, 6) == round(1_400.0 * 2 / 120.0, 6)
    assert second_trade.qty > first_trade.qty
    assert round(result.account.equity, 6) == 1_960.0


def test_single_run_orchestrator_assembles_manifest_run_and_metrics() -> None:
    candles = _sample_candles()
    signals = [
        _signal(
            signal_id="sig-open",
            timestamp=candles[0].timestamp,
            action=SignalAction.OPEN,
            side=Side.LONG,
        ),
        _signal(
            signal_id="sig-close",
            timestamp=candles[1].timestamp,
            action=SignalAction.CLOSE,
            side=Side.LONG,
        ),
    ]
    orchestrator = SingleRunOrchestrator()

    result = orchestrator.execute(
        request=SingleRunRequest(
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
            fee_model_params_json={"rate": 0.001},
            slippage_model_params_json={"bps": 0},
            benchmark_config_json={"benchmark_type": "buy_and_hold"},
            resolved_config_json={"qty_policy": "fixed_1", "seed": 7},
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

    assert result.run.status.value == "success"
    assert result.run.config_hash
    assert result.manifest.run_id == "run-001"
    assert result.metrics.trade_count == 1
    assert result.metrics.final_equity == result.execution.account.equity


def _sample_candles() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [
        (100.0, 101.0, 99.0, 100.0),
        (102.0, 103.0, 101.0, 102.0),
        (105.0, 106.0, 104.0, 105.0),
    ]
    candles: list[CanonicalCandle] = []
    for index, (open_price, high, low, close) in enumerate(prices):
        candles.append(
            CanonicalCandle(
                timestamp=start + timedelta(hours=index),
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=10.0,
                price_type=PriceType.LAST,
            )
        )
    return candles


def _sample_candles_for_dynamic_sizing() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [
        (100.0, 100.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (120.0, 121.0, 119.0, 120.0),
        (120.0, 121.0, 119.0, 120.0),
        (144.0, 145.0, 143.0, 144.0),
    ]
    candles: list[CanonicalCandle] = []
    for index, (open_price, high, low, close) in enumerate(prices):
        candles.append(
            CanonicalCandle(
                timestamp=start + timedelta(hours=index),
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=10.0,
                price_type=PriceType.LAST,
            )
        )
    return candles


def _signal(
    *,
    signal_id: str,
    timestamp: datetime,
    action: SignalAction,
    side: Side,
) -> SignalIntent:
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
