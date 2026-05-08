"""Paper-trading workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from crypto_backtest_workbench.app.paper_trading.broker import PaperBroker
from crypto_backtest_workbench.app.paper_trading.market_data import PaperMarketDataClient
from crypto_backtest_workbench.app.paper_trading.models import PaperSession, PaperTickResult
from crypto_backtest_workbench.app.paper_trading.repository import FilePaperTradingRepository
from crypto_backtest_workbench.app.paper_trading.timeframe_aggregation import (
    aggregate_complete_execution_candles,
    merge_complete_execution_strategy_candles,
    timeframe_delta,
)
from crypto_backtest_workbench.app.workflows.execution_verification import (
    _execution_constraints_from_config,
    _map_signals_to_execution_timeline,
)
from crypto_backtest_workbench.app.workflows.run_backtest import build_strategy
from crypto_backtest_workbench.domain.models import CanonicalCandle
from crypto_backtest_workbench.engine.data.fetchers import HistoryFetcher
from crypto_backtest_workbench.engine.features import FeaturePipeline
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot
from crypto_backtest_workbench.engine.strategy import StrategyInput
from crypto_backtest_workbench.storage.repositories import FeatureRepository, RunRepository


DEFAULT_PAPER_STRATEGY_LOOKBACK_BARS = 500
DEFAULT_PAPER_EXECUTION_LOOKBACK_BARS = 600


@dataclass(slots=True, frozen=True)
class CreatePaperSessionRequest:
    stable_candidate_id: str
    source_run_id: str
    session_id: str | None = None
    initial_cash: float | None = None
    exchange: str | None = None
    symbol: str | None = None
    market_type: str | None = None
    price_type: str | None = None
    strategy_timeframe: str | None = None
    execution_timeframe: str = "5m"


@dataclass(slots=True, frozen=True)
class TickPaperSessionRequest:
    session_id: str
    until: datetime | None = None
    strategy_candles: list[CanonicalCandle] | None = None
    execution_candles: list[CanonicalCandle] | None = None


def create_paper_session_workflow(
    *,
    paper_repository: FilePaperTradingRepository,
    run_repository: RunRepository,
    request: CreatePaperSessionRequest,
) -> PaperSession:
    run = run_repository.load_run(request.source_run_id)
    manifest = run_repository.load_manifest(request.source_run_id)
    config = dict(manifest.resolved_config_json)
    execution_constraints = _require_dict(config.get("execution_constraints"), "execution_constraints")
    if request.initial_cash is not None:
        execution_constraints["initial_cash"] = float(request.initial_cash)
    initial_cash = float(execution_constraints.get("initial_cash", 10_000.0))
    strategy_params = _require_dict(config.get("strategy_params"), "strategy_params")
    strategy_timeframe = request.strategy_timeframe or str(config.get("strategy_timeframe") or config.get("timeframe") or "1h")
    session = PaperSession(
        session_id=request.session_id or _build_paper_session_id(request.stable_candidate_id, request.source_run_id),
        stable_candidate_id=request.stable_candidate_id,
        source_run_id=request.source_run_id,
        strategy_name=run.strategy_name,
        symbol=request.symbol or str(config.get("symbol") or ""),
        exchange=request.exchange or str(config.get("exchange") or "binance"),
        market_type=request.market_type or str(config.get("market_type") or "linear_usdt_perpetual"),
        price_type=request.price_type or str(config.get("price_type") or "last"),
        strategy_timeframe=strategy_timeframe,
        execution_timeframe=request.execution_timeframe,
        strategy_params=strategy_params,
        execution_constraints=execution_constraints,
        account=AccountSnapshot(
            available_cash=initial_cash,
            used_margin=0.0,
            maintenance_margin=0.0,
            equity=initial_cash,
            unrealized_pnl=0.0,
        ),
    )
    if not session.symbol:
        raise ValueError("paper session requires a symbol")
    paper_repository.save_session(session)
    return session


def tick_paper_session_workflow(
    *,
    paper_repository: FilePaperTradingRepository,
    feature_repository: FeatureRepository,
    market_data_client: PaperMarketDataClient | None = None,
    request: TickPaperSessionRequest,
) -> PaperTickResult:
    session = paper_repository.load_session(request.session_id)
    if session.status != "active":
        raise ValueError(f"paper session is not active: {session.status}")
    until = request.until or datetime.now(UTC)

    strategy_candles = request.strategy_candles
    execution_candles = request.execution_candles
    if strategy_candles is None or execution_candles is None:
        if market_data_client is None:
            raise ValueError("market_data_client is required when candles are not supplied")
        if execution_candles is None:
            execution_candles = market_data_client.fetch_closed_candles(
                exchange=session.exchange,
                symbol=session.symbol,
                market_type=session.market_type,
                price_type=session.price_type,
                timeframe=session.execution_timeframe,
                since=_fetch_since(
                    session.checkpoint.last_execution_bar_time,
                    session.execution_timeframe,
                    DEFAULT_PAPER_EXECUTION_LOOKBACK_BARS,
                ),
                until=until,
            )
        if strategy_candles is None:
            strategy_candles = market_data_client.fetch_closed_candles(
                exchange=session.exchange,
                symbol=session.symbol,
                market_type=session.market_type,
                price_type=session.price_type,
                timeframe=session.strategy_timeframe,
                since=_fetch_since(
                    session.checkpoint.last_strategy_bar_time,
                    session.strategy_timeframe,
                    DEFAULT_PAPER_STRATEGY_LOOKBACK_BARS,
                ),
                until=until,
            )
            strategy_candles = _merge_closed_execution_strategy_candles(
                session=session,
                strategy_candles=strategy_candles,
                execution_candles=execution_candles or [],
                until=until,
            )

    strategy_candles = _new_or_all_candles(strategy_candles, after=session.checkpoint.last_strategy_bar_time, warmup=True)
    execution_candles = _new_or_all_candles(execution_candles, after=session.checkpoint.last_execution_bar_time, warmup=False)
    if not execution_candles:
        paper_repository.save_session(session)
        return PaperTickResult(session, len(strategy_candles), len(execution_candles), 0, 0, 0, 0, 0, [], [], [], [])

    latest_strategy_bar_time = max((candle.timestamp for candle in strategy_candles), default=None)
    mapped_signals = []
    if strategy_candles:
        strategy = build_strategy({"strategy_name": session.strategy_name, **session.strategy_params})
        feature_artifact = FeaturePipeline(feature_repository).materialize(
            dataset_snapshot_id=(
                f"paper:{session.session_id}:{session.strategy_timeframe}:"
                f"{latest_strategy_bar_time.isoformat()}:{len(strategy_candles)}"
            ),
            candles=strategy_candles,
            specs=strategy.feature_specs(),
            depends_on=(session.source_run_id,),
        )
        raw_signals = strategy.generate_signals(
            StrategyInput(
                run_id=session.session_id,
                symbol=session.symbol,
                timeframe=session.strategy_timeframe,
                feature_artifact_id=feature_artifact.feature_artifact_id,
                features_uri=feature_artifact.storage_uri,
                config={"qty_policy_ref": str(session.strategy_params.get("qty_policy_ref") or "percent_of_cash")},
            )
        )
        new_raw_signals = [
            signal
            for signal in raw_signals
            if session.checkpoint.last_signal_time is None or signal.timestamp > session.checkpoint.last_signal_time
        ]
        mapped_signals = _map_signals_to_execution_timeline(new_raw_signals, execution_candles)
    else:
        new_raw_signals = []
    constraints = _execution_constraints_from_config(session.execution_constraints)
    broker_result = PaperBroker().execute(
        session=session,
        execution_candles=execution_candles,
        signals=mapped_signals,
        constraints=constraints,
    )
    session.position = broker_result.position
    if latest_strategy_bar_time is not None:
        session.checkpoint.last_strategy_bar_time = latest_strategy_bar_time
    session.checkpoint.last_execution_bar_time = max(candle.timestamp for candle in execution_candles)
    if new_raw_signals:
        session.checkpoint.last_signal_time = max(signal.timestamp for signal in new_raw_signals)
    session.checkpoint.execution_bar_count += len(execution_candles)
    session.updated_at = datetime.now(UTC)
    paper_repository.save_session(session)
    paper_repository.append_orders(session.session_id, broker_result.orders)
    paper_repository.append_fills(session.session_id, broker_result.fills)
    paper_repository.append_trades(session.session_id, broker_result.trades)
    paper_repository.append_warnings(session.session_id, broker_result.warnings)
    return PaperTickResult(
        session=session,
        strategy_bar_count=len(strategy_candles),
        execution_bar_count=len(execution_candles),
        new_signal_count=len(mapped_signals),
        order_count=len(broker_result.orders),
        fill_count=len(broker_result.fills),
        closed_trade_count=len(broker_result.trades),
        warning_count=len(broker_result.warnings),
        orders=broker_result.orders,
        fills=broker_result.fills,
        trades=broker_result.trades,
        warnings=broker_result.warnings,
    )


def build_default_market_data_client(fetcher: HistoryFetcher) -> PaperMarketDataClient:
    return PaperMarketDataClient(fetcher)


def _new_or_all_candles(candles: list[CanonicalCandle], *, after: datetime | None, warmup: bool) -> list[CanonicalCandle]:
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp)
    if after is None:
        return sorted_candles
    if warmup:
        newer = [candle for candle in sorted_candles if candle.timestamp > after]
        if not newer:
            return []
        first_new_index = sorted_candles.index(newer[0])
        start_index = max(0, first_new_index - DEFAULT_PAPER_STRATEGY_LOOKBACK_BARS)
        return sorted_candles[start_index:]
    return [candle for candle in sorted_candles if candle.timestamp > after]


def _fetch_since(last_seen: datetime | None, timeframe: str, bars: int) -> datetime:
    if last_seen is not None:
        return last_seen - (timeframe_delta(timeframe) * max(1, bars))
    return datetime.fromtimestamp(0, tz=UTC)


def _merge_closed_execution_strategy_candles(
    *,
    session: PaperSession,
    strategy_candles: list[CanonicalCandle],
    execution_candles: list[CanonicalCandle],
    until: datetime,
) -> list[CanonicalCandle]:
    return merge_complete_execution_strategy_candles(
        strategy_candles=strategy_candles,
        execution_candles=execution_candles,
        source_timeframe=session.execution_timeframe,
        target_timeframe=session.strategy_timeframe,
        until=until,
    )


def _aggregate_complete_execution_candles(
    candles: list[CanonicalCandle],
    *,
    source_timeframe: str,
    target_timeframe: str,
    until: datetime,
) -> list[CanonicalCandle]:
    return aggregate_complete_execution_candles(
        candles,
        source_timeframe=source_timeframe,
        target_timeframe=target_timeframe,
        until=until,
    )


def _build_paper_session_id(stable_candidate_id: str, source_run_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"paper-{_safe_id_part(stable_candidate_id)}-{_safe_id_part(source_run_id)}-{timestamp}"


def _require_dict(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"source run missing {field_name}")
    return dict(value)


def _safe_id_part(value: str) -> str:
    text = value.strip().lower()
    chars = [char if char.isalnum() or char in {"-", "_", "."} else "-" for char in text]
    compact = "-".join(part for part in "".join(chars).split("-") if part)
    return compact[:80] or "item"
