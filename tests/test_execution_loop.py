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


def test_simulate_signals_risk_pct_of_equity_sizes_qty_from_stop_distance() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.qty_policy_ref = "risk_pct_of_equity"
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=2.0, stop_mult=1.5, rr=2.0, min_stop_pct=0.01)

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            risk_pct_per_trade_by_policy={"risk_pct_of_equity": 0.01},
        ),
    )

    trade = result.trades[0]
    assert round(trade.qty, 6) == round(10.0 / 3.0, 6)
    assert trade.planned_stop_loss_price == 97.0
    assert trade.planned_take_profit_price == 106.0


def test_simulate_signals_risk_pct_of_equity_respects_margin_cap() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.qty_policy_ref = "risk_pct_of_equity"
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=0.01, stop_mult=1.0, rr=2.0, min_stop_pct=0.0001)

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            risk_pct_per_trade_by_policy={"risk_pct_of_equity": 0.5},
        ),
    )

    trade = result.trades[0]
    assert round(trade.qty, 6) == 10.0


def test_simulate_signals_risk_pct_of_cash_allocation_sizes_within_allocated_cash() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.qty_policy_ref = "risk_pct_of_cash_allocation"
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=2.0, stop_mult=1.5, rr=2.0, min_stop_pct=0.01)

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=10.0,
            fee_rate=0.0,
            cash_allocation_pct_by_policy={"risk_pct_of_cash_allocation": 50.0},
            risk_pct_per_trade_by_policy={"risk_pct_of_cash_allocation": 0.1},
        ),
    )

    trade = result.trades[0]
    assert round(trade.qty, 6) == round(50.0 / 3.0, 6)


def test_simulate_signals_risk_pct_of_cash_allocation_respects_cash_cap() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.qty_policy_ref = "risk_pct_of_cash_allocation"
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=0.01, stop_mult=1.0, rr=2.0, min_stop_pct=0.0001)

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            cash_allocation_pct_by_policy={"risk_pct_of_cash_allocation": 50.0},
            risk_pct_per_trade_by_policy={"risk_pct_of_cash_allocation": 0.5},
        ),
    )

    trade = result.trades[0]
    assert round(trade.qty, 6) == 5.0


def test_simulate_signals_risk_pct_of_equity_requires_risk_spec() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.qty_policy_ref = "risk_pct_of_equity"

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            risk_pct_per_trade_by_policy={"risk_pct_of_equity": 0.01},
        ),
    )

    assert len(result.orders) == 1
    assert result.orders[0].status == "rejected"
    assert result.orders[0].reject_reason_code is not None
    assert result.trades == []


def test_simulate_signals_without_risk_spec_keeps_v1_execution_behavior() -> None:
    candles = _sample_candles_for_risk_management()
    signals = [
        _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG),
    ]

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_time is None
    assert result.trades[0].planned_stop_loss_price is None
    assert result.trades[0].planned_take_profit_price is None


def test_simulate_signals_risk_spec_uses_true_fill_price_for_planned_sltp() -> None:
    candles = _sample_candles_for_risk_management()
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=2.0, stop_mult=1.5, rr=2.0, min_stop_pct=0.01)

    result = simulate_signals(
        candles=candles[:2],
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            slippage_bps=100.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    trade = result.trades[0]
    assert trade.entry_price == 101.0
    assert trade.planned_stop_loss_price == 98.0
    assert trade.planned_take_profit_price == 107.0


def test_simulate_signals_same_bar_new_short_position_checks_stop_loss_intrabar() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _risk_candle(start, 0, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 1, (100.0, 110.0, 99.0, 105.0)),
        _risk_candle(start, 2, (120.0, 121.0, 119.0, 120.0)),
    ]
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.SHORT)
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=3.0, stop_mult=1.0, rr=2.0, min_stop_pct=0.0)

    result = simulate_signals(
        candles=candles,
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    trade = result.trades[0]
    assert trade.entry_time == candles[1].timestamp
    assert trade.exit_time == candles[1].timestamp
    assert trade.exit_reason == "stop_loss_intrabar"
    assert trade.exit_price == 103.0


def test_simulate_signals_same_bar_new_position_prefers_stop_when_stop_and_tp_trigger() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _risk_candle(start, 0, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 1, (100.0, 107.0, 96.0, 101.0)),
    ]
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG)
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=3.0, stop_mult=1.0, rr=2.0, min_stop_pct=0.0)

    result = simulate_signals(
        candles=candles,
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )

    trade = result.trades[0]
    assert trade.exit_time == candles[1].timestamp
    assert trade.exit_reason == "stop_loss_intrabar"
    assert trade.exit_price == 97.0


def test_simulate_signals_cooldown_skips_open_after_short_stop_loss() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _risk_candle(start, 0, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 1, (100.0, 101.0, 96.0, 100.0)),
        _risk_candle(start, 2, (100.0, 101.0, 96.0, 100.0)),
        _risk_candle(start, 3, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 4, (100.0, 101.0, 96.0, 100.0)),
    ]
    signals = [
        _signal(signal_id="sig-open-1", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG),
        _signal(signal_id="sig-open-2", timestamp=candles[1].timestamp, action=SignalAction.OPEN, side=Side.LONG),
        _signal(signal_id="sig-open-3", timestamp=candles[3].timestamp, action=SignalAction.OPEN, side=Side.LONG),
    ]
    for signal in signals:
        signal.meta_json["risk_spec"] = _risk_spec(atr_value=3.0, stop_mult=1.0, rr=2.0, min_stop_pct=0.0)

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
            cooldown_after_consecutive_stop_losses=1,
            cooldown_bars=2,
            cooldown_only_short_holding_bars=3,
        ),
    )

    assert len(result.trades) == 2
    assert all(trade.exit_reason == "stop_loss_intrabar" for trade in result.trades)
    assert all(trade.holding_bars == 0 for trade in result.trades)
    assert [warning.warning_code for warning in result.warnings] == ["OPEN_SKIPPED_DRAWDOWN_PROTECTION"]


def test_simulate_signals_long_stop_loss_intrabar() -> None:
    trade = _run_risk_case(side=Side.LONG, trigger_bar=(100.0, 104.0, 96.0, 101.0), rr=2.0)
    assert trade.exit_reason == "stop_loss_intrabar"
    assert trade.exit_price == 97.0


def test_simulate_signals_short_stop_loss_intrabar() -> None:
    trade = _run_risk_case(side=Side.SHORT, trigger_bar=(100.0, 104.0, 96.0, 101.0), rr=2.0)
    assert trade.exit_reason == "stop_loss_intrabar"
    assert trade.exit_price == 103.0


def test_simulate_signals_long_take_profit_intrabar() -> None:
    trade = _run_risk_case(side=Side.LONG, trigger_bar=(100.0, 107.0, 99.0, 106.0), rr=2.0)
    assert trade.exit_reason == "take_profit_intrabar"
    assert trade.exit_price == 106.0


def test_simulate_signals_short_take_profit_intrabar() -> None:
    trade = _run_risk_case(side=Side.SHORT, trigger_bar=(100.0, 101.0, 93.0, 94.0), rr=2.0)
    assert trade.exit_reason == "take_profit_intrabar"
    assert trade.exit_price == 94.0


def test_simulate_signals_long_stop_loss_gap_open() -> None:
    trade = _run_risk_case(side=Side.LONG, trigger_bar=(95.0, 100.0, 94.0, 99.0), rr=2.0)
    assert trade.exit_reason == "stop_loss_gap_open"
    assert trade.exit_price == 95.0


def test_simulate_signals_short_stop_loss_gap_open() -> None:
    trade = _run_risk_case(side=Side.SHORT, trigger_bar=(105.0, 106.0, 100.0, 101.0), rr=2.0)
    assert trade.exit_reason == "stop_loss_gap_open"
    assert trade.exit_price == 105.0


def test_simulate_signals_long_take_profit_gap_open() -> None:
    trade = _run_risk_case(side=Side.LONG, trigger_bar=(108.0, 109.0, 100.0, 101.0), rr=2.0)
    assert trade.exit_reason == "take_profit_gap_open"
    assert trade.exit_price == 108.0


def test_simulate_signals_short_take_profit_gap_open() -> None:
    trade = _run_risk_case(side=Side.SHORT, trigger_bar=(92.0, 100.0, 91.0, 99.0), rr=2.0)
    assert trade.exit_reason == "take_profit_gap_open"
    assert trade.exit_price == 92.0


def test_simulate_signals_same_bar_stop_and_take_profit_prefers_stop() -> None:
    trade = _run_risk_case(side=Side.LONG, trigger_bar=(100.0, 107.0, 96.0, 101.0), rr=2.0)
    assert trade.exit_reason == "stop_loss_intrabar"
    assert trade.exit_price == 97.0


def test_simulate_signals_tolerates_margin_precision_at_full_cash_allocation() -> None:
    candles = _sample_candles_for_margin_precision()
    signals = [
        _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=Side.LONG),
        _signal(signal_id="sig-close", timestamp=candles[1].timestamp, action=SignalAction.CLOSE, side=Side.LONG),
    ]
    for signal in signals:
        signal.qty_policy_ref = "percent_of_cash"

    result = simulate_signals(
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=10_000.0,
            leverage=3.0,
            fee_rate=0.0,
            cash_allocation_pct_by_policy={"percent_of_cash": 100.0},
        ),
    )

    assert len(result.orders) == 2
    assert all(order.status == "filled" for order in result.orders)
    assert all(order.reject_reason_code is None for order in result.orders)
    assert len(result.fills) == 2
    assert len(result.trades) == 1


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


def _sample_candles_for_margin_precision() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [
        (45_000.0, 45_100.0, 44_900.0, 45_000.0),
        (45_001.3, 45_100.0, 44_900.0, 45_001.3),
        (45_010.0, 45_100.0, 44_900.0, 45_010.0),
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


def _sample_candles_for_risk_management() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
    ]
    return [
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
        for index, (open_price, high, low, close) in enumerate(prices)
    ]


def _run_risk_case(*, side: Side, trigger_bar: tuple[float, float, float, float], rr: float) -> object:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _risk_candle(start, 0, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 1, (100.0, 101.0, 99.0, 100.0)),
        _risk_candle(start, 2, trigger_bar),
    ]
    signal = _signal(signal_id="sig-open", timestamp=candles[0].timestamp, action=SignalAction.OPEN, side=side)
    signal.meta_json["risk_spec"] = _risk_spec(atr_value=3.0, stop_mult=1.0, rr=rr, min_stop_pct=0.0)

    result = simulate_signals(
        candles=candles,
        signals=[signal],
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=1.0,
            fee_rate=0.0,
            qty_by_policy={"fixed_1": 1.0},
        ),
    )
    assert len(result.trades) == 1
    return result.trades[0]


def _risk_candle(start: datetime, index: int, prices: tuple[float, float, float, float]) -> CanonicalCandle:
    open_price, high, low, close = prices
    return CanonicalCandle(
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


def _risk_spec(*, atr_value: float, stop_mult: float, rr: float, min_stop_pct: float) -> dict[str, object]:
    return {
        "stop_loss_mode": "atr_multiple",
        "stop_loss_value": stop_mult,
        "take_profit_mode": "rr",
        "take_profit_value": rr,
        "atr_value": atr_value,
        "min_stop_pct": min_stop_pct,
    }


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
