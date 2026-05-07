"""Realtime kline stream cache for paper trading."""

from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from crypto_backtest_workbench.domain.models import CanonicalCandle, MarketType, PriceType, now_utc
from crypto_backtest_workbench.engine.data.canonicalizer import sort_and_deduplicate_candles


@dataclass(frozen=True, slots=True)
class LiveKlineStreamSpec:
    exchange: str
    symbol: str
    market_type: MarketType
    timeframe: str
    price_type: PriceType = PriceType.LAST


class FileLiveKlineCache:
    """Append-only closed-kline cache backed by local CSV files."""

    CSV_FIELDS = (
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
    )

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def ingest_binance_message(self, spec: LiveKlineStreamSpec, payload: dict[str, Any]) -> CanonicalCandle | None:
        event = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(event, dict):
            return None
        kline = event.get("k")
        if not isinstance(kline, dict):
            return None

        status = {
            "exchange": spec.exchange,
            "symbol": spec.symbol,
            "market_type": spec.market_type.value,
            "timeframe": spec.timeframe,
            "price_type": spec.price_type.value,
            "status": "connected",
            "last_message_at": now_utc().isoformat(),
            "updated_at": now_utc().isoformat(),
        }
        if not bool(kline.get("x")):
            self.save_status(spec, status)
            return None

        candle = CanonicalCandle(
            timestamp=datetime.fromtimestamp(int(kline["t"]) / 1000, tz=UTC),
            symbol=spec.symbol,
            exchange=spec.exchange,
            market_type=spec.market_type,
            timeframe=spec.timeframe,
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            price_type=spec.price_type,
            data_source="binance_ws",
        )
        self.save_candles(spec, [candle])
        status["last_closed_bar_time"] = candle.timestamp.isoformat()
        self.save_status(spec, status)
        return candle

    def load_candles(
        self,
        spec: LiveKlineStreamSpec,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[CanonicalCandle]:
        path = self._candles_path(spec)
        if not path.exists():
            return []
        candles: list[CanonicalCandle] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                candle = _row_to_candle(row)
                if not _matches_spec(candle, spec):
                    continue
                if since is not None and candle.timestamp < since:
                    continue
                if until is not None and candle.timestamp >= until:
                    continue
                candles.append(candle)
        return sort_and_deduplicate_candles(candles)

    def save_candles(self, spec: LiveKlineStreamSpec, candles: list[CanonicalCandle]) -> None:
        if not candles:
            return
        merged = sort_and_deduplicate_candles([*self.load_candles(spec), *candles])
        path = self._candles_path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for candle in merged:
                writer.writerow(_candle_to_row(candle))

    def load_status(self, spec: LiveKlineStreamSpec) -> dict[str, object]:
        path = self._status_path(spec)
        if not path.exists():
            return {
                "exchange": spec.exchange,
                "symbol": spec.symbol,
                "market_type": spec.market_type.value,
                "timeframe": spec.timeframe,
                "price_type": spec.price_type.value,
                "status": "idle",
            }
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save_status(self, spec: LiveKlineStreamSpec, status: dict[str, object]) -> None:
        path = self._status_path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self.load_status(spec), **status, "updated_at": now_utc().isoformat()}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)

    def _candles_path(self, spec: LiveKlineStreamSpec) -> Path:
        return self._spec_dir(spec) / "closed_candles.csv"

    def _status_path(self, spec: LiveKlineStreamSpec) -> Path:
        return self._spec_dir(spec) / "status.json"

    def _spec_dir(self, spec: LiveKlineStreamSpec) -> Path:
        return (
            self.data_dir
            / "paper_trading"
            / "live_klines"
            / _safe_path_part(spec.exchange)
            / _safe_path_part(spec.symbol)
            / _safe_path_part(spec.timeframe)
            / _safe_path_part(spec.price_type.value)
        )


async def stream_binance_usdm_klines(
    *,
    cache: FileLiveKlineCache,
    specs: list[LiveKlineStreamSpec],
    on_closed_candle: Callable[[LiveKlineStreamSpec, CanonicalCandle], None] | None = None,
    message_timeout_seconds: float = 45.0,
    reconnect_delay_seconds: float = 5.0,
) -> None:
    """Stream Binance USD-M closed klines into the local cache until cancelled."""

    if not specs:
        return
    import aiohttp

    stream_to_spec = {f"{_binance_stream_symbol(spec.symbol)}@kline_{spec.timeframe}": spec for spec in specs}
    streams = "/".join(stream_to_spec)
    url = f"wss://fstream.binance.com/market/stream?streams={streams}"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=180) as websocket:
                    for spec in specs:
                        cache.save_status(
                            spec,
                            {
                                "status": "connecting",
                                "stream_url": url,
                                "connected_at": now_utc().isoformat(),
                                "error": None,
                            },
                        )
                    while True:
                        try:
                            message = await websocket.receive(timeout=message_timeout_seconds)
                        except TimeoutError:
                            for spec in specs:
                                cache.save_status(
                                    spec,
                                    {
                                        "status": "stale",
                                        "stream_url": url,
                                        "error": f"no websocket messages within {message_timeout_seconds:g}s",
                                    },
                                )
                            break
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(message.data)
                            stream = str(payload.get("stream") or "")
                            spec = stream_to_spec.get(stream)
                            if spec is not None:
                                candle = cache.ingest_binance_message(spec, payload)
                                if candle is not None and on_closed_candle is not None:
                                    on_closed_candle(spec, candle)
                        elif message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE}:
                            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - depends on network/runtime availability
            for spec in specs:
                cache.save_status(
                    spec,
                    {
                        "status": "error",
                        "stream_url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            await asyncio.sleep(reconnect_delay_seconds)


def _candle_to_row(candle: CanonicalCandle) -> dict[str, object]:
    return {
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


def _row_to_candle(row: dict[str, str]) -> CanonicalCandle:
    return CanonicalCandle(
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
        data_source=row.get("data_source") or "binance_ws",
    )


def _matches_spec(candle: CanonicalCandle, spec: LiveKlineStreamSpec) -> bool:
    return (
        candle.symbol == spec.symbol
        and _exchange_alias(candle.exchange) == _exchange_alias(spec.exchange)
        and candle.market_type == spec.market_type
        and candle.timeframe == spec.timeframe
        and candle.price_type == spec.price_type
    )


def _binance_stream_symbol(symbol: str) -> str:
    return symbol.split(":", 1)[0].replace("/", "").lower()


def _exchange_alias(exchange: str) -> str:
    return "binanceusdm" if exchange in {"binance", "binanceusdm"} else exchange


def _safe_path_part(value: str) -> str:
    chars = [char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value.strip()]
    compact = "_".join(part for part in "".join(chars).split("_") if part)
    return compact[:120] or "unknown"
