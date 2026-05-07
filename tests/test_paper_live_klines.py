from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from crypto_backtest_workbench.app.paper_trading.live_klines import FileLiveKlineCache, LiveKlineStreamSpec
from crypto_backtest_workbench.app.paper_trading.market_data import PaperLocalKlineMarketDataClient
from crypto_backtest_workbench.domain.models import MarketType, PriceType


def test_binance_kline_cache_persists_only_closed_klines(tmp_path: Path) -> None:
    cache = FileLiveKlineCache(tmp_path)
    spec = _spec()

    assert cache.ingest_binance_message(spec, _binance_payload(is_closed=False, close="101.0")) is None
    assert cache.load_candles(spec) == []

    candle = cache.ingest_binance_message(spec, _binance_payload(is_closed=True, close="102.0"))

    assert candle is not None
    assert candle.timestamp == datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
    assert candle.close == 102.0
    assert cache.load_candles(spec)[0].data_source == "binance_ws"
    status = cache.load_status(spec)
    assert status["status"] == "connected"
    assert status["last_closed_bar_time"] == "2026-05-07T08:00:00+00:00"


def test_local_market_data_client_merges_dataset_and_live_cache(tmp_path: Path) -> None:
    spec = _spec()
    _write_dataset(tmp_path, spec)
    cache = FileLiveKlineCache(tmp_path)
    cache.ingest_binance_message(spec, _binance_payload(is_closed=True, close="103.0", open_time_ms=1778141400000))
    client = PaperLocalKlineMarketDataClient(data_dir=tmp_path, live_cache=cache)

    candles = client.fetch_closed_candles(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        market_type=MarketType.LINEAR_USDT_PERPETUAL.value,
        price_type=PriceType.LAST.value,
        timeframe="5m",
        since=datetime(2026, 5, 7, 8, 0, tzinfo=UTC),
        until=datetime(2026, 5, 7, 9, 0, tzinfo=UTC),
    )

    assert [candle.close for candle in candles] == [100.0, 101.0, 103.0]
    assert candles[-1].data_source == "binance_ws"


def test_closed_kline_callback_runs_after_cache_ingest(tmp_path: Path) -> None:
    cache = FileLiveKlineCache(tmp_path)
    spec = _spec()
    events = []

    candle = cache.ingest_binance_message(spec, _binance_payload(is_closed=True, close="104.0"))
    if candle is not None:
        events.append((spec.timeframe, candle.timestamp.isoformat()))

    assert events == [("5m", "2026-05-07T08:00:00+00:00")]
    assert cache.load_candles(spec)[0].close == 104.0


def _spec() -> LiveKlineStreamSpec:
    return LiveKlineStreamSpec(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        timeframe="5m",
        price_type=PriceType.LAST,
    )


def _binance_payload(*, is_closed: bool, close: str, open_time_ms: int = 1778140800000) -> dict[str, object]:
    return {
        "stream": "btcusdt@kline_5m",
        "data": {
            "e": "kline",
            "E": open_time_ms + 1,
            "s": "BTCUSDT",
            "k": {
                "t": open_time_ms,
                "T": open_time_ms + 299999,
                "s": "BTCUSDT",
                "i": "5m",
                "o": "100.0",
                "c": close,
                "h": "104.0",
                "l": "99.0",
                "v": "12.5",
                "x": is_closed,
            },
        },
    }


def _write_dataset(tmp_path: Path, spec: LiveKlineStreamSpec) -> None:
    dataset_dir = tmp_path / "datasets" / "binanceusdm-BTC_USDT_USDT-5m-fixture"
    dataset_dir.mkdir(parents=True)
    snapshot = {
        "dataset_snapshot_id": "binanceusdm-BTC_USDT_USDT-5m-fixture",
        "exchange": spec.exchange,
        "market_type": spec.market_type.value,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "price_type": spec.price_type.value,
    }
    (dataset_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    with (dataset_dir / "canonical_candles.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FileLiveKlineCache.CSV_FIELDS)
        writer.writeheader()
        for index, close in enumerate([100.0, 101.0]):
            writer.writerow(
                {
                    "timestamp": datetime(2026, 5, 7, 8, index * 5, tzinfo=UTC).isoformat(),
                    "symbol": spec.symbol,
                    "exchange": spec.exchange,
                    "market_type": spec.market_type.value,
                    "timeframe": spec.timeframe,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "price_type": spec.price_type.value,
                    "data_source": "fixture",
                }
            )
