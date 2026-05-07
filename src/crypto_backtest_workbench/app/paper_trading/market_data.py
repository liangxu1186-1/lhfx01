"""Market-data helpers for paper trading."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from crypto_backtest_workbench.domain.models import CanonicalCandle, MarketType, PriceType, now_utc
from crypto_backtest_workbench.engine.data.canonicalizer import (
    drop_open_last_candle,
    ohlcv_rows_to_canonical_candles,
    sort_and_deduplicate_candles,
)
from crypto_backtest_workbench.engine.data.fetchers import HistoryFetchRequest, HistoryFetcher

from .live_klines import FileLiveKlineCache, LiveKlineStreamSpec


class PaperMarketDataClient:
    """Fetch and normalize closed candles for paper trading."""

    def __init__(self, fetcher: HistoryFetcher) -> None:
        self.fetcher = fetcher

    def fetch_closed_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        market_type: str,
        timeframe: str,
        since: datetime,
        until: datetime | None = None,
        price_type: str = "last",
        limit: int = 1000,
    ) -> list[CanonicalCandle]:
        request = HistoryFetchRequest(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            market_type=MarketType(market_type),
            since=since,
            until=until,
            limit=limit,
            price_type=PriceType(price_type),
        )
        rows = self.fetcher.fetch_ohlcv(request)
        candles = ohlcv_rows_to_canonical_candles(
            rows,
            exchange=exchange,
            symbol=symbol,
            market_type=MarketType(market_type),
            timeframe=timeframe,
            price_type=PriceType(price_type),
            data_source=getattr(self.fetcher, "data_source", "paper_rest"),
        )
        closed, _ = drop_open_last_candle(candles, now=until or now_utc())
        return closed


class PaperLocalKlineMarketDataClient:
    """Read paper-trading candles from local datasets and realtime WS cache first."""

    def __init__(
        self,
        *,
        data_dir: Path,
        live_cache: FileLiveKlineCache | None = None,
        rest_client: PaperMarketDataClient | None = None,
        allow_rest_fallback: bool = False,
    ) -> None:
        self.data_dir = data_dir
        self.live_cache = live_cache
        self.rest_client = rest_client
        self.allow_rest_fallback = allow_rest_fallback

    def fetch_closed_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        market_type: str,
        timeframe: str,
        since: datetime,
        until: datetime | None = None,
        price_type: str = "last",
        limit: int = 1000,
    ) -> list[CanonicalCandle]:
        spec = LiveKlineStreamSpec(
            exchange=_exchange_alias(exchange),
            symbol=symbol,
            market_type=MarketType(market_type),
            timeframe=timeframe,
            price_type=PriceType(price_type),
        )
        candles = [
            *self._load_dataset_candles(spec, since=since, until=until),
            *(self.live_cache.load_candles(spec, since=since, until=until) if self.live_cache else []),
        ]
        closed, _ = drop_open_last_candle(sort_and_deduplicate_candles(candles), now=until or now_utc())
        if closed or not self.allow_rest_fallback or self.rest_client is None:
            return closed[-limit:]
        return self.rest_client.fetch_closed_candles(
            exchange=exchange,
            symbol=symbol,
            market_type=market_type,
            timeframe=timeframe,
            since=since,
            until=until,
            price_type=price_type,
            limit=limit,
        )

    def _load_dataset_candles(
        self,
        spec: LiveKlineStreamSpec,
        *,
        since: datetime,
        until: datetime | None,
    ) -> list[CanonicalCandle]:
        candles: list[CanonicalCandle] = []
        datasets_dir = self.data_dir / "datasets"
        if not datasets_dir.exists():
            return []
        for snapshot_path in datasets_dir.glob("*/snapshot.json"):
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not _snapshot_matches_spec(snapshot, spec):
                continue
            candles.extend(_load_candle_csv(snapshot_path.parent / "canonical_candles.csv", spec, since=since, until=until))
        return sort_and_deduplicate_candles(candles)


def _snapshot_matches_spec(snapshot: dict[str, object], spec: LiveKlineStreamSpec) -> bool:
    return (
        str(snapshot.get("symbol") or "") == spec.symbol
        and _exchange_alias(str(snapshot.get("exchange") or "")) == _exchange_alias(spec.exchange)
        and str(snapshot.get("market_type") or "") == spec.market_type.value
        and str(snapshot.get("timeframe") or "") == spec.timeframe
        and str(snapshot.get("price_type") or "last") == spec.price_type.value
    )


def _load_candle_csv(
    path: Path,
    spec: LiveKlineStreamSpec,
    *,
    since: datetime,
    until: datetime | None,
) -> list[CanonicalCandle]:
    if not path.exists():
        return []
    candles: list[CanonicalCandle] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candle = CanonicalCandle(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                symbol=row["symbol"],
                exchange=row["exchange"],
                market_type=MarketType(row["market_type"]),
                timeframe=row["timeframe"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                price_type=PriceType(row.get("price_type") or "last"),
                data_source=row.get("data_source") or "local_dataset",
            )
            if not _candle_matches_spec(candle, spec):
                continue
            if candle.timestamp < since:
                continue
            if until is not None and candle.timestamp >= until:
                continue
            candles.append(candle)
    return candles


def _candle_matches_spec(candle: CanonicalCandle, spec: LiveKlineStreamSpec) -> bool:
    return (
        candle.symbol == spec.symbol
        and _exchange_alias(candle.exchange) == _exchange_alias(spec.exchange)
        and candle.market_type == spec.market_type
        and candle.timeframe == spec.timeframe
        and candle.price_type == spec.price_type
    )


def _exchange_alias(exchange: str) -> str:
    return "binanceusdm" if exchange in {"binance", "binanceusdm"} else exchange
