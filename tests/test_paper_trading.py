from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_backtest_workbench.app.paper_trading import (
    CreatePaperSessionRequest,
    FilePaperTradingRepository,
    TickPaperSessionRequest,
    create_paper_session_workflow,
    tick_paper_session_workflow,
)
from crypto_backtest_workbench.app.paper_trading.broker import PaperBroker
from crypto_backtest_workbench.app.paper_trading.models import PaperCheckpoint, PaperSession
from crypto_backtest_workbench.app.paper_trading.repository import FilePaperTradingRepository
from crypto_backtest_workbench.domain.models import (
    BacktestRun,
    CanonicalCandle,
    MarketType,
    PriceType,
    RunManifest,
    Side,
    SignalAction,
    SignalIntent,
    TaskStatus,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot
from crypto_backtest_workbench.storage.repositories import FileFeatureRepository, FileRunRepository


def test_paper_broker_opens_on_next_execution_bar_and_marks_position() -> None:
    session = _session()
    candles = _candles([100.0, 101.0, 102.0])
    signal = _signal(timestamp=candles[0].timestamp)

    result = PaperBroker().execute(
        session=session,
        execution_candles=candles,
        signals=[signal],
        constraints=ExecutionConstraints(initial_cash=1_000.0, leverage=2.0, qty_by_policy={"fixed_1": 1.0}),
    )

    assert len(result.orders) == 1
    assert len(result.fills) == 1
    assert result.position is not None
    assert result.position.trade.entry_time == candles[1].timestamp
    assert result.position.reserved_margin == 50.5
    assert session.account.available_cash == 949.5
    assert session.account.used_margin == 50.5
    assert session.account.equity == 1001.0


def test_paper_broker_closes_for_intrabar_stop_loss_before_take_profit() -> None:
    session = _session()
    candles = _candles([100.0, 100.0])
    signal = _signal(
        timestamp=candles[0].timestamp,
        meta_json={
            "risk_spec": {
                "stop_loss_mode": "atr_multiple",
                "stop_loss_value": 1.0,
                "take_profit_mode": "rr",
                "take_profit_value": 2.0,
                "atr_value": 10.0,
                "min_stop_pct": 0.0,
            }
        },
    )
    execution_candle = CanonicalCandle(
        timestamp=candles[1].timestamp,
        symbol="BTC/USDT:USDT",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        timeframe="5m",
        open=100.0,
        high=130.0,
        low=80.0,
        close=90.0,
        volume=1.0,
        price_type=PriceType.LAST,
        data_source="fixture",
    )

    result = PaperBroker().execute(
        session=session,
        execution_candles=[candles[0], execution_candle],
        signals=[signal],
        constraints=ExecutionConstraints(initial_cash=1_000.0, leverage=1.0, qty_by_policy={"fixed_1": 1.0}),
    )

    assert result.position is None
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_loss_intrabar"
    assert result.trades[0].exit_price == 90.0
    assert result.trades[0].net_pnl == -10.0
    assert session.account.equity == 990.0


def test_paper_repository_round_trips_open_position(tmp_path: Path) -> None:
    repository = FilePaperTradingRepository(tmp_path)
    session = _session()
    candles = _candles([100.0, 101.0])
    result = PaperBroker().execute(
        session=session,
        execution_candles=candles,
        signals=[_signal(timestamp=candles[0].timestamp)],
        constraints=ExecutionConstraints(initial_cash=1_000.0, leverage=2.0, qty_by_policy={"fixed_1": 1.0}),
    )
    session.position = result.position
    session.checkpoint = PaperCheckpoint(last_execution_bar_time=candles[-1].timestamp, execution_bar_count=2)

    repository.save_session(session)
    loaded = repository.load_session(session.session_id)

    assert loaded.session_id == session.session_id
    assert loaded.position is not None
    assert loaded.position.trade.entry_time == candles[1].timestamp
    assert loaded.account.available_cash == 949.5
    assert loaded.checkpoint.execution_bar_count == 2


def test_create_paper_session_inherits_source_run_config(tmp_path: Path) -> None:
    run_repository = FileRunRepository(tmp_path)
    _persist_source_run(run_repository)
    paper_repository = FilePaperTradingRepository(tmp_path)

    session = create_paper_session_workflow(
        paper_repository=paper_repository,
        run_repository=run_repository,
        request=CreatePaperSessionRequest(
            session_id="paper-api-001",
            stable_candidate_id="stable-001",
            source_run_id="run-source-001",
            initial_cash=2_000.0,
        ),
    )

    assert session.session_id == "paper-api-001"
    assert session.strategy_name == "ema_crossover"
    assert session.account.equity == 2_000.0
    assert session.execution_constraints["initial_cash"] == 2_000.0
    assert paper_repository.load_session("paper-api-001").stable_candidate_id == "stable-001"


def test_tick_processes_execution_bars_without_new_strategy_bars(tmp_path: Path) -> None:
    repository = FilePaperTradingRepository(tmp_path)
    session = _session()
    initial_candles = _candles([100.0, 100.0])
    open_result = PaperBroker().execute(
        session=session,
        execution_candles=initial_candles,
        signals=[
            _signal(
                timestamp=initial_candles[0].timestamp,
                meta_json={
                    "risk_spec": {
                        "stop_loss_mode": "atr_multiple",
                        "stop_loss_value": 1.0,
                        "take_profit_mode": "rr",
                        "take_profit_value": 2.0,
                        "atr_value": 5.0,
                        "min_stop_pct": 0.0,
                    }
                },
            )
        ],
        constraints=ExecutionConstraints(initial_cash=1_000.0, leverage=2.0, qty_by_policy={"fixed_1": 1.0}),
    )
    session.position = open_result.position
    session.checkpoint.last_execution_bar_time = initial_candles[-1].timestamp
    session.checkpoint.execution_bar_count = len(initial_candles)
    repository.save_session(session)
    stop_candle = CanonicalCandle(
        timestamp=initial_candles[-1].timestamp + timedelta(minutes=5),
        symbol="BTC/USDT:USDT",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        timeframe="5m",
        open=100.0,
        high=101.0,
        low=90.0,
        close=95.0,
        volume=1.0,
        price_type=PriceType.LAST,
        data_source="fixture",
    )

    result = tick_paper_session_workflow(
        paper_repository=repository,
        feature_repository=FileFeatureRepository(tmp_path),
        request=TickPaperSessionRequest(
            session_id=session.session_id,
            strategy_candles=[],
            execution_candles=[stop_candle],
        ),
    )

    assert result.new_signal_count == 0
    assert result.closed_trade_count == 1
    assert result.session.position is None
    assert repository.load_session(session.session_id).position is None


def _session() -> PaperSession:
    return PaperSession(
        session_id="paper-test-001",
        stable_candidate_id="stable-001",
        source_run_id="run-source-001",
        strategy_name="ema_crossover",
        symbol="BTC/USDT:USDT",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL.value,
        price_type=PriceType.LAST.value,
        strategy_timeframe="1h",
        execution_timeframe="5m",
        strategy_params={"qty_policy_ref": "fixed_1"},
        execution_constraints={"initial_cash": 1_000.0, "leverage": 2.0, "qty_by_policy": {"fixed_1": 1.0}},
        account=AccountSnapshot(
            available_cash=1_000.0,
            used_margin=0.0,
            maintenance_margin=0.0,
            equity=1_000.0,
            unrealized_pnl=0.0,
        ),
    )


def _signal(*, timestamp: datetime, meta_json: dict[str, object] | None = None) -> SignalIntent:
    return SignalIntent(
        signal_id=f"signal-{timestamp.isoformat()}",
        run_id="paper-test-001",
        timestamp=timestamp,
        symbol="BTC/USDT:USDT",
        action=SignalAction.OPEN,
        side=Side.LONG,
        qty_policy_ref="fixed_1",
        reason_code="manual_open",
        meta_json=meta_json or {},
    )


def _candles(closes: list[float]) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, close in enumerate(closes):
        candles.append(
            CanonicalCandle(
                timestamp=start + timedelta(minutes=5 * index),
                symbol="BTC/USDT:USDT",
                exchange="binanceusdm",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="5m",
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1.0,
                price_type=PriceType.LAST,
                data_source="fixture",
            )
        )
    return candles


def _persist_source_run(repository: FileRunRepository) -> None:
    created_at = datetime(2024, 1, 1, tzinfo=UTC)
    run = BacktestRun(
        run_id="run-source-001",
        strategy_name="ema_crossover",
        strategy_version="v1",
        dataset_snapshot_id="snapshot-source-001",
        execution_policy_id="execution-v1",
        metric_policy_id="metric-v1",
        feature_artifact_id="feature-001",
        engine_version="engine-v1",
        fee_model_version="fee-v1",
        slippage_model_version="slippage-v1",
        fee_model_params_json={},
        slippage_model_params_json={},
        validation_split_id="validation:none",
        config_hash="hash",
        resolved_config_uri="memory://resolved",
        benchmark_config_uri="memory://benchmark",
        seed=None,
        run_manifest_uri="memory://manifest",
        status=TaskStatus.SUCCESS,
        created_at=created_at,
    )
    manifest = RunManifest(
        run_id="run-source-001",
        dataset_snapshot_id="snapshot-source-001",
        strategy_version="v1",
        engine_version="engine-v1",
        execution_policy_id="execution-v1",
        metric_policy_id="metric-v1",
        feature_artifact_id="feature-001",
        validation_split_id="validation:none",
        fee_model_version="fee-v1",
        slippage_model_version="slippage-v1",
        fee_model_params_json={},
        slippage_model_params_json={},
        benchmark_config_json={},
        resolved_config_json={
            "symbol": "BTC/USDT:USDT",
            "exchange": "binanceusdm",
            "market_type": MarketType.LINEAR_USDT_PERPETUAL.value,
            "price_type": PriceType.LAST.value,
            "timeframe": "1h",
            "strategy_params": {"fast_period": 2, "slow_period": 3, "qty_policy_ref": "fixed_1"},
            "execution_constraints": {
                "initial_cash": 1_000.0,
                "leverage": 2.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "qty_by_policy": {"fixed_1": 1.0},
            },
        },
        seed=None,
        created_at=created_at,
    )
    repository.save_run(run)
    repository.save_manifest(manifest)
