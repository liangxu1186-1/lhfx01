"""Paper-trading signal snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import floor

from crypto_backtest_workbench.app.paper_trading.live_klines import FileLiveKlineCache, LiveKlineStreamSpec
from crypto_backtest_workbench.app.paper_trading.market_data import PaperLocalKlineMarketDataClient
from crypto_backtest_workbench.app.paper_trading.models import PaperSession
from crypto_backtest_workbench.app.paper_trading.timeframe_aggregation import (
    merge_complete_execution_strategy_candles,
    timeframe_delta,
)
from crypto_backtest_workbench.app.workflows.execution_verification import _execution_constraints_from_config
from crypto_backtest_workbench.domain.models import CanonicalCandle, MarketType, PriceType, Side
from crypto_backtest_workbench.engine.data.canonicalizer import ohlcv_rows_to_canonical_candles
from crypto_backtest_workbench.engine.data.fetchers import (
    BinanceUsdMRestHistoryFetcher,
    HistoryFetchRequest,
    OhlcvRow,
)
from crypto_backtest_workbench.engine.features.indicators import compute_atr, compute_ema


DEFAULT_STRATEGY_LOOKBACK_BARS = 600
DEFAULT_EXECUTION_LOOKBACK_BARS = 900
MAX_BACKFILL_BARS = 300


@dataclass(slots=True, frozen=True)
class BackfillStatus:
    attempted: bool
    status: str
    timeframe: str
    requested_since: datetime | None = None
    requested_until: datetime | None = None
    fetched_bars: int = 0
    error: str | None = None


def build_paper_signal_snapshot(
    *,
    session: PaperSession,
    data_dir,
    allow_backfill: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = now or datetime.now(UTC)
    live_cache = FileLiveKlineCache(data_dir)
    local_client = PaperLocalKlineMarketDataClient(data_dir=data_dir, live_cache=live_cache)
    backfill_status = BackfillStatus(attempted=False, status="disabled", timeframe=session.execution_timeframe)

    execution_candles = _load_execution_candles(session=session, local_client=local_client, now=current_time)
    if allow_backfill:
        backfill_status = _backfill_execution_gap(session=session, data_dir=data_dir, live_cache=live_cache, existing=execution_candles, now=current_time)
        execution_candles = _load_execution_candles(session=session, local_client=local_client, now=current_time)

    strategy_candles = _load_strategy_candles(
        session=session,
        local_client=local_client,
        execution_candles=execution_candles,
        now=current_time,
    )
    indicators = _compute_strategy_indicators(strategy_candles, session.strategy_params)
    execution_latest = execution_candles[-1] if execution_candles else None
    last_strategy = strategy_candles[-1] if strategy_candles else None
    previous_strategy = strategy_candles[-2] if len(strategy_candles) >= 2 else None
    side, trigger_price, trigger_distance = _trigger_state(last_strategy, previous_strategy, indicators, session.strategy_params)
    estimated_entry = execution_latest.close if execution_latest is not None else (last_strategy.close if last_strategy is not None else None)
    risk = _risk_snapshot(session=session, side=side, entry_price=estimated_entry, atr=indicators.get("atr"))
    gap = _gap_status(execution_candles, session.execution_timeframe)

    return {
        "session_id": session.session_id,
        "symbol": session.symbol,
        "strategy_timeframe": session.strategy_timeframe,
        "execution_timeframe": session.execution_timeframe,
        "generated_at": current_time.isoformat(),
        "data": {
            "source": "local_dataset_ws_cache",
            "strategy_bar_count": len(strategy_candles),
            "execution_bar_count": len(execution_candles),
            "last_strategy_bar_time": last_strategy.timestamp.isoformat() if last_strategy else None,
            "last_execution_bar_time": execution_latest.timestamp.isoformat() if execution_latest else None,
            "execution_gap_count": gap["gap_count"],
            "latest_gap_start": gap["latest_gap_start"],
            "latest_gap_end": gap["latest_gap_end"],
        },
        "indicators": indicators,
        "trigger": {
            "side": side.value if side else None,
            "status": _trigger_status(side=side, trigger_distance=trigger_distance, last_strategy=last_strategy),
            "trigger_price": trigger_price,
            "distance_to_trigger": trigger_distance,
            "last_close": last_strategy.close if last_strategy else None,
            "previous_high": previous_strategy.high if previous_strategy else None,
            "previous_low": previous_strategy.low if previous_strategy else None,
        },
        "estimate": {
            "entry_price": estimated_entry,
            **risk,
        },
        "backfill": {
            "attempted": backfill_status.attempted,
            "status": backfill_status.status,
            "timeframe": backfill_status.timeframe,
            "requested_since": backfill_status.requested_since.isoformat() if backfill_status.requested_since else None,
            "requested_until": backfill_status.requested_until.isoformat() if backfill_status.requested_until else None,
            "fetched_bars": backfill_status.fetched_bars,
            "error": backfill_status.error,
        },
    }


def _load_execution_candles(*, session: PaperSession, local_client: PaperLocalKlineMarketDataClient, now: datetime) -> list[CanonicalCandle]:
    return local_client.fetch_closed_candles(
        exchange=session.exchange,
        symbol=session.symbol,
        market_type=session.market_type,
        price_type=session.price_type,
        timeframe=session.execution_timeframe,
        since=now - (timeframe_delta(session.execution_timeframe) * DEFAULT_EXECUTION_LOOKBACK_BARS),
        until=now,
        limit=DEFAULT_EXECUTION_LOOKBACK_BARS,
    )


def _load_strategy_candles(
    *,
    session: PaperSession,
    local_client: PaperLocalKlineMarketDataClient,
    execution_candles: list[CanonicalCandle],
    now: datetime,
) -> list[CanonicalCandle]:
    strategy_candles = local_client.fetch_closed_candles(
        exchange=session.exchange,
        symbol=session.symbol,
        market_type=session.market_type,
        price_type=session.price_type,
        timeframe=session.strategy_timeframe,
        since=now - (timeframe_delta(session.strategy_timeframe) * DEFAULT_STRATEGY_LOOKBACK_BARS),
        until=now,
        limit=DEFAULT_STRATEGY_LOOKBACK_BARS,
    )
    strategy_candles = merge_complete_execution_strategy_candles(
        strategy_candles=strategy_candles,
        execution_candles=execution_candles,
        source_timeframe=session.execution_timeframe,
        target_timeframe=session.strategy_timeframe,
        until=now,
    )
    return strategy_candles[-DEFAULT_STRATEGY_LOOKBACK_BARS:]


def _compute_strategy_indicators(candles: list[CanonicalCandle], params: dict[str, object]) -> dict[str, float | None]:
    closes = [candle.close for candle in candles]
    fast_period = int(params.get("trend_fast_period", 2))
    slow_period = int(params.get("trend_slow_period", 13))
    entry_period = int(params.get("entry_ema_period", 21))
    atr_period = int(params.get("atr_period", 14))
    fast = compute_ema(closes, fast_period)
    slow = compute_ema(closes, slow_period)
    entry = compute_ema(closes, entry_period)
    atr = compute_atr(candles, atr_period)
    return {
        "ema_fast_period": float(fast_period),
        "ema_slow_period": float(slow_period),
        "entry_ema_period": float(entry_period),
        "atr_period": float(atr_period),
        "ema_fast": _last_number(fast),
        "ema_slow": _last_number(slow),
        "ema21": _last_number(entry),
        "atr": _last_number(atr),
    }


def _trigger_state(
    last: CanonicalCandle | None,
    previous: CanonicalCandle | None,
    indicators: dict[str, float | None],
    params: dict[str, object],
) -> tuple[Side | None, float | None, float | None]:
    if last is None or previous is None:
        return None, None, None
    ema_fast = indicators.get("ema_fast")
    ema_slow = indicators.get("ema_slow")
    entry_ema = indicators.get("ema21")
    atr = indicators.get("atr")
    if ema_fast is None or ema_slow is None or entry_ema is None or atr is None:
        return None, None, None
    tolerance = float(params.get("atr_entry_tolerance", 1.0))
    long_touch = abs(last.low - entry_ema) <= atr * tolerance
    short_touch = abs(last.high - entry_ema) <= atr * tolerance
    if ema_fast > ema_slow and long_touch:
        return Side.LONG, previous.high, max(0.0, previous.high - last.close)
    if ema_fast < ema_slow and short_touch:
        return Side.SHORT, previous.low, max(0.0, last.close - previous.low)
    if ema_fast > ema_slow:
        return Side.LONG, previous.high, max(0.0, previous.high - last.close)
    if ema_fast < ema_slow:
        return Side.SHORT, previous.low, max(0.0, last.close - previous.low)
    return None, None, None


def _trigger_status(*, side: Side | None, trigger_distance: float | None, last_strategy: CanonicalCandle | None) -> str:
    if side is None or trigger_distance is None or last_strategy is None:
        return "insufficient_data"
    if trigger_distance <= 0:
        return "triggered_on_latest_strategy_bar"
    return "waiting"


def _risk_snapshot(*, session: PaperSession, side: Side | None, entry_price: float | None, atr: float | None) -> dict[str, float | None]:
    if side is None or entry_price is None or atr is None:
        return {
            "stop_loss": None,
            "take_profit": None,
            "stop_distance": None,
            "qty": None,
            "notional": None,
            "margin": None,
        }
    params = session.strategy_params
    constraints = _execution_constraints_from_config(session.execution_constraints)
    stop_mult = float(params.get("atr_stop_mult", 1.0))
    reward_ratio = float(params.get("risk_reward_ratio", 1.0))
    min_stop_pct = float(params.get("min_stop_pct", 0.0))
    stop_distance = max(atr * stop_mult, entry_price * min_stop_pct)
    if side is Side.LONG:
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + (stop_distance * reward_ratio)
    else:
        stop_loss = entry_price + stop_distance
        take_profit = entry_price - (stop_distance * reward_ratio)
    qty = _estimate_qty(session=session, entry_price=entry_price, stop_distance=stop_distance)
    notional = entry_price * qty if qty is not None else None
    margin = notional / constraints.leverage if notional is not None and constraints.leverage else None
    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_distance": stop_distance,
        "qty": qty,
        "notional": notional,
        "margin": margin,
    }


def _estimate_qty(*, session: PaperSession, entry_price: float, stop_distance: float) -> float | None:
    constraints = _execution_constraints_from_config(session.execution_constraints)
    policy = str(session.strategy_params.get("qty_policy_ref") or "percent_of_cash")
    cash_allocation_pct = constraints.cash_allocation_pct_by_policy.get(policy)
    risk_pct = constraints.risk_pct_per_trade_by_policy.get(policy)
    if risk_pct is not None:
        risk_cash_base = session.account.available_cash
        if cash_allocation_pct is not None:
            risk_cash_base = session.account.available_cash * (cash_allocation_pct / 100)
        risk_qty = (risk_cash_base * risk_pct) / stop_distance if stop_distance > 0 else 0.0
        allocation_qty = _cash_allocation_qty(
            price=entry_price,
            leverage=constraints.leverage,
            fee_rate=constraints.fee_rate,
            available_cash=session.account.available_cash,
            cash_allocation_pct=cash_allocation_pct or 100.0,
        )
        return min(risk_qty, allocation_qty)
    if cash_allocation_pct is not None:
        return _cash_allocation_qty(
            price=entry_price,
            leverage=constraints.leverage,
            fee_rate=constraints.fee_rate,
            available_cash=session.account.available_cash,
            cash_allocation_pct=cash_allocation_pct,
        )
    return constraints.qty_by_policy.get(policy)


def _cash_allocation_qty(*, price: float, leverage: float, fee_rate: float, available_cash: float, cash_allocation_pct: float) -> float:
    if price <= 0 or leverage <= 0:
        return 0.0
    allocated_cash = available_cash * (cash_allocation_pct / 100)
    notional_cost_per_unit = (1 / leverage) + fee_rate
    if allocated_cash <= 0 or notional_cost_per_unit <= 0:
        return 0.0
    return (allocated_cash / notional_cost_per_unit) / price


def _backfill_execution_gap(
    *,
    session: PaperSession,
    data_dir,
    live_cache: FileLiveKlineCache,
    existing: list[CanonicalCandle],
    now: datetime,
) -> BackfillStatus:
    if _exchange_alias(session.exchange) != "binanceusdm":
        return BackfillStatus(attempted=True, status="unsupported_exchange", timeframe=session.execution_timeframe)
    if session.execution_timeframe not in {"5m", "15m"}:
        return BackfillStatus(attempted=True, status="unsupported_timeframe", timeframe=session.execution_timeframe)
    if not existing:
        return BackfillStatus(attempted=True, status="skipped_no_local_anchor", timeframe=session.execution_timeframe)
    execution_delta = timeframe_delta(session.execution_timeframe)
    since, until = _latest_missing_range(existing, execution_delta, now)
    if since >= until:
        return BackfillStatus(attempted=True, status="up_to_date", timeframe=session.execution_timeframe, requested_since=since, requested_until=until)
    max_until = min(until, since + (execution_delta * MAX_BACKFILL_BARS))
    try:
        fetcher = BinanceUsdMRestHistoryFetcher(request_pause_seconds=1.0, retry_backoff_seconds=10.0, max_rate_limit_retries=1)
        rows = fetcher.fetch_ohlcv(
            HistoryFetchRequest(
                exchange="binanceusdm",
                symbol=session.symbol,
                timeframe=session.execution_timeframe,
                market_type=MarketType(session.market_type),
                price_type=PriceType(session.price_type),
                since=since,
                until=max_until,
                limit=200,
            )
        )
        candles = ohlcv_rows_to_canonical_candles(
            rows,
            exchange="binanceusdm",
            symbol=session.symbol,
            market_type=MarketType(session.market_type),
            timeframe=session.execution_timeframe,
            price_type=PriceType(session.price_type),
            data_source="binance_rest_backfill",
        )
        live_cache.save_candles(_live_spec(session, session.execution_timeframe), candles)
        return BackfillStatus(
            attempted=True,
            status="success",
            timeframe=session.execution_timeframe,
            requested_since=since,
            requested_until=max_until,
            fetched_bars=len(candles),
        )
    except Exception as exc:
        return BackfillStatus(
            attempted=True,
            status="error",
            timeframe=session.execution_timeframe,
            requested_since=since,
            requested_until=max_until,
            error=f"{type(exc).__name__}: {exc}",
        )


def _gap_status(candles: list[CanonicalCandle], timeframe: str) -> dict[str, object]:
    if len(candles) < 2:
        return {"gap_count": 0, "latest_gap_start": None, "latest_gap_end": None}
    expected_delta = timeframe_delta(timeframe)
    gaps: list[tuple[datetime, datetime]] = []
    for left, right in zip(candles, candles[1:]):
        if right.timestamp - left.timestamp > expected_delta:
            gaps.append((left.timestamp + expected_delta, right.timestamp))
    latest = gaps[-1] if gaps else None
    return {
        "gap_count": len(gaps),
        "latest_gap_start": latest[0].isoformat() if latest else None,
        "latest_gap_end": latest[1].isoformat() if latest else None,
    }


def _latest_missing_range(candles: list[CanonicalCandle], expected_delta: timedelta, now: datetime) -> tuple[datetime, datetime]:
    for left, right in reversed(list(zip(candles, candles[1:]))):
        if right.timestamp - left.timestamp > expected_delta:
            return left.timestamp + expected_delta, right.timestamp
    last_next = candles[-1].timestamp + expected_delta
    return last_next, _floor_time(now, expected_delta)


def _live_spec(session: PaperSession, timeframe: str) -> LiveKlineStreamSpec:
    return LiveKlineStreamSpec(
        exchange=_exchange_alias(session.exchange),
        symbol=session.symbol,
        market_type=MarketType(session.market_type),
        timeframe=timeframe,
        price_type=PriceType(session.price_type),
    )


def _floor_time(value: datetime, delta: timedelta) -> datetime:
    seconds = int(delta.total_seconds())
    timestamp = floor(value.timestamp() / seconds) * seconds
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _last_number(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return float(value)
    return None


def _exchange_alias(exchange: str) -> str:
    return "binanceusdm" if exchange in {"binance", "binanceusdm"} else exchange
