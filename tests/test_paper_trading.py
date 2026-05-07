from __future__ import annotations

import json
import csv
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
from crypto_backtest_workbench.app.paper_trading.market_data import PaperLocalKlineMarketDataClient
from crypto_backtest_workbench.app.paper_trading.models import PaperCheckpoint, PaperSession
from crypto_backtest_workbench.app.paper_trading.repository import FilePaperTradingRepository
from crypto_backtest_workbench.app.paper_trading.workflows import _aggregate_complete_execution_candles_to_1h
from crypto_backtest_workbench.app.paper_trading.signal_snapshot import build_paper_signal_snapshot
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


def test_paper_broker_executes_signal_mapped_to_current_incremental_bar() -> None:
    session = _session()
    candles = _candles([100.0, 101.0])
    signal = _signal(
        timestamp=candles[1].timestamp,
        meta_json={"execution_signal_timestamp": candles[1].timestamp.isoformat()},
    )

    result = PaperBroker().execute(
        session=session,
        execution_candles=[candles[1]],
        signals=[signal],
        constraints=ExecutionConstraints(initial_cash=1_000.0, leverage=2.0, qty_by_policy={"fixed_1": 1.0}),
    )

    assert len(result.orders) == 1
    assert len(result.fills) == 1
    assert result.position is not None
    assert result.position.trade.entry_time == candles[1].timestamp


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


def test_signal_snapshot_aggregates_5m_execution_candles_to_1h(tmp_path: Path) -> None:
    session = _session(
        strategy_name="ema_pullback_atr_v2",
        strategy_params={
            "trend_fast_period": 2,
            "trend_slow_period": 13,
            "entry_ema_period": 21,
            "atr_period": 14,
            "atr_entry_tolerance": 1.0,
            "atr_stop_mult": 2.0,
            "risk_reward_ratio": 1.5,
            "min_stop_pct": 0.003,
            "qty_policy_ref": "risk_pct_of_cash_allocation",
        },
        execution_constraints={
            "initial_cash": 10_000.0,
            "leverage": 10.0,
            "fee_rate": 0.0,
            "min_notional": 0.0,
            "cash_allocation_pct_by_policy": {"risk_pct_of_cash_allocation": 50.0},
            "risk_pct_per_trade_by_policy": {"risk_pct_of_cash_allocation": 0.1},
        },
    )
    _write_execution_dataset(tmp_path, session, _candles([100.0 + index for index in range(360)]))

    snapshot = build_paper_signal_snapshot(
        session=session,
        data_dir=tmp_path,
        now=datetime(2024, 1, 2, 7, 0, tzinfo=UTC),
    )

    assert snapshot["data"]["strategy_bar_count"] == 30
    assert snapshot["indicators"]["ema_fast_period"] == 2.0
    assert snapshot["indicators"]["ema_slow_period"] == 13.0
    assert snapshot["indicators"]["entry_ema_period"] == 21.0
    assert snapshot["indicators"]["atr"] is not None
    assert snapshot["estimate"]["entry_price"] is not None
    assert snapshot["backfill"]["attempted"] is False


def test_paper_tick_merges_only_complete_1h_from_execution_candles(tmp_path: Path) -> None:
    repository = FilePaperTradingRepository(tmp_path)
    session = _session(strategy_params={"fast_period": 2, "slow_period": 3, "qty_policy_ref": "fixed_1"})
    repository.save_session(session)
    execution_candles = _candles([100.0 + index for index in range(24)])
    _write_execution_dataset(tmp_path, session, execution_candles)
    client = PaperLocalKlineMarketDataClient(data_dir=tmp_path)

    result = tick_paper_session_workflow(
        paper_repository=repository,
        feature_repository=FileFeatureRepository(tmp_path),
        market_data_client=client,
        request=TickPaperSessionRequest(
            session_id=session.session_id,
            until=datetime(2024, 1, 1, 1, 30, tzinfo=UTC),
        ),
    )

    assert result.strategy_bar_count == 1
    assert result.session.checkpoint.last_strategy_bar_time == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert result.session.checkpoint.last_execution_bar_time == datetime(2024, 1, 1, 1, 25, tzinfo=UTC)


def test_aggregate_complete_execution_candles_to_1h_skips_partial_or_gapped_buckets() -> None:
    candles = _candles([100.0 + index for index in range(24)])

    aggregated = _aggregate_complete_execution_candles_to_1h(
        candles,
        source_timeframe="5m",
        until=datetime(2024, 1, 1, 1, 30, tzinfo=UTC),
    )
    gapped = _aggregate_complete_execution_candles_to_1h(
        [candle for index, candle in enumerate(candles[:12]) if index != 4],
        source_timeframe="5m",
        until=datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
    )

    assert [candle.timestamp for candle in aggregated] == [datetime(2024, 1, 1, 0, 0, tzinfo=UTC)]
    assert aggregated[0].open == 100.0
    assert aggregated[0].close == 111.0
    assert aggregated[0].timeframe == "1h"
    assert gapped == []


def test_signal_snapshot_backfill_targets_latest_internal_gap(tmp_path: Path, monkeypatch) -> None:
    session = _session()
    _write_execution_dataset(
        tmp_path,
        session,
        [
            *_candles([100.0, 101.0]),
            *[
                CanonicalCandle(
                    timestamp=datetime(2024, 1, 1, 1, 0, tzinfo=UTC) + timedelta(minutes=5 * index),
                    symbol="BTC/USDT:USDT",
                    exchange="binanceusdm",
                    market_type=MarketType.LINEAR_USDT_PERPETUAL,
                    timeframe="5m",
                    open=110.0 + index,
                    high=111.0 + index,
                    low=109.0 + index,
                    close=110.0 + index,
                    volume=1.0,
                    price_type=PriceType.LAST,
                    data_source="fixture",
                )
                for index in range(2)
            ],
        ],
    )
    captured: dict[str, datetime] = {}

    def fake_fetch(self, request):
        captured["since"] = request.since
        captured["until"] = request.until
        return []

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.paper_trading.signal_snapshot.BinanceUsdMRestHistoryFetcher.fetch_ohlcv",
        fake_fetch,
    )

    snapshot = build_paper_signal_snapshot(
        session=session,
        data_dir=tmp_path,
        allow_backfill=True,
        now=datetime(2024, 1, 1, 2, 0, tzinfo=UTC),
    )

    assert captured["since"] == datetime(2024, 1, 1, 0, 10, tzinfo=UTC)
    assert captured["until"] == datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
    assert snapshot["backfill"]["status"] == "success"


def _session(
    *,
    strategy_name: str = "ema_crossover",
    strategy_params: dict[str, object] | None = None,
    execution_constraints: dict[str, object] | None = None,
) -> PaperSession:
    return PaperSession(
        session_id="paper-test-001",
        stable_candidate_id="stable-001",
        source_run_id="run-source-001",
        strategy_name=strategy_name,
        symbol="BTC/USDT:USDT",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL.value,
        price_type=PriceType.LAST.value,
        strategy_timeframe="1h",
        execution_timeframe="5m",
        strategy_params=strategy_params or {"qty_policy_ref": "fixed_1"},
        execution_constraints=execution_constraints or {"initial_cash": 1_000.0, "leverage": 2.0, "qty_by_policy": {"fixed_1": 1.0}},
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


def _write_execution_dataset(tmp_path: Path, session: PaperSession, candles: list[CanonicalCandle]) -> None:
    dataset_dir = tmp_path / "datasets" / "binanceusdm-BTC_USDT_USDT-5m-fixture"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "dataset_snapshot_id": "binanceusdm-BTC_USDT_USDT-5m-fixture",
                "exchange": session.exchange,
                "market_type": session.market_type,
                "symbol": session.symbol,
                "timeframe": session.execution_timeframe,
                "price_type": session.price_type,
            }
        ),
        encoding="utf-8",
    )
    with (dataset_dir / "canonical_candles.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "symbol",
                "exchange",
                "market_type",
                "timeframe",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "price_type",
                "data_source",
            ],
        )
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle.timestamp.isoformat(),
                    "symbol": candle.symbol,
                    "exchange": candle.exchange,
                    "market_type": candle.market_type.value,
                    "timeframe": candle.timeframe,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "price_type": candle.price_type.value,
                    "data_source": candle.data_source,
                }
            )
