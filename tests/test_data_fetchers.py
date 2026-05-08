from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json

from crypto_backtest_workbench.domain.models import MarketType
from crypto_backtest_workbench.engine.data.fetchers import (
    BinanceUsdMRestHistoryFetcher,
    CcxtHistoryFetcher,
    FallbackHistoryFetcher,
    HistoryFetchRequest,
    OhlcvRow,
)
from crypto_backtest_workbench.engine.data.service import DatasetIngestionService


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(_dt(year, month, day, hour, minute).timestamp() * 1000)


def _raw_row(timestamp_ms: int, close: float) -> list[float]:
    return [timestamp_ms, close - 1.0, close + 1.0, close - 2.0, close, 10.0]


class FakeExchangeClient:
    def __init__(self, pages: list[list[list[float]]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        *,
        since: int,
        limit: int,
        params: dict[str, object],
    ) -> list[list[float]]:
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "since": since,
                "limit": limit,
                "params": dict(params),
            }
        )
        if not self._pages:
            return []
        return self._pages.pop(0)


class FakeHistoryFetcher:
    def __init__(self, rows: list[OhlcvRow]) -> None:
        self._rows = rows
        self.data_source = "fake_fetcher"

    def fetch_ohlcv(self, request: HistoryFetchRequest) -> list[OhlcvRow]:
        return list(self._rows)


class FailingHistoryFetcher:
    def __init__(self, message: str = "primary failed") -> None:
        self.message = message
        self.data_source = "primary_source"

    def fetch_ohlcv(self, request: HistoryFetchRequest) -> list[OhlcvRow]:
        raise RuntimeError(self.message)


class FakeResponse:
    def __init__(self, payload: object, *, status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            response = requests.Response()
            response.status_code = self.status_code
            response.url = "https://fapi.binance.com/fapi/v1/klines"
            raise requests.HTTPError(f"{self.status_code} error", response=response)
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: float):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        if not self.payloads:
            return FakeResponse([])
        payload = self.payloads.pop(0)
        if isinstance(payload, FakeResponse):
            return payload
        return FakeResponse(payload)


class FakeDatasetRepository:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        return self.base_dir / snapshot_id

    def save_snapshot(self, snapshot) -> Path:
        directory = self._snapshot_dir(snapshot.dataset_snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "snapshot.json"
        path.write_text(json.dumps({"dataset_snapshot_id": snapshot.dataset_snapshot_id}), encoding="utf-8")
        return path

    def save_candles(self, snapshot_id: str, candles: list[object]) -> Path:
        directory = self._snapshot_dir(snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "canonical_candles.csv"
        path.write_text("timestamp\n", encoding="utf-8")
        return path

    def save_integrity_report(self, report) -> Path:
        directory = self._snapshot_dir(report.dataset_snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "integrity_report.json"
        path.write_text(json.dumps({"dataset_snapshot_id": report.dataset_snapshot_id}), encoding="utf-8")
        return path


def test_ccxt_history_fetcher_paginates_with_until_and_deduplicates() -> None:
    client = FakeExchangeClient(
        pages=[
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
                _raw_row(_ms(2024, 1, 1, 1), 101.0),
            ],
            [
                _raw_row(_ms(2024, 1, 1, 1), 101.0),
                _raw_row(_ms(2024, 1, 1, 2), 102.0),
            ],
            [
                _raw_row(_ms(2024, 1, 1, 3), 103.0),
                _raw_row(_ms(2024, 1, 1, 4), 104.0),
            ],
        ]
    )
    fetcher = CcxtHistoryFetcher(client)
    request = HistoryFetchRequest(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 3, 30),
        limit=2,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [
        _ms(2024, 1, 1, 0),
        _ms(2024, 1, 1, 1),
        _ms(2024, 1, 1, 2),
        _ms(2024, 1, 1, 3),
    ]
    assert [call["since"] for call in client.calls] == [
        _ms(2024, 1, 1, 0),
        _ms(2024, 1, 1, 2),
        _ms(2024, 1, 1, 3),
    ]


def test_ccxt_history_fetcher_stops_when_exchange_repeats_same_page() -> None:
    repeated_page = [
        _raw_row(_ms(2024, 1, 1, 0), 100.0),
        _raw_row(_ms(2024, 1, 1, 1), 101.0),
    ]
    client = FakeExchangeClient(pages=[repeated_page, repeated_page])
    fetcher = CcxtHistoryFetcher(client)
    request = HistoryFetchRequest(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        limit=2,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [
        _ms(2024, 1, 1, 0),
        _ms(2024, 1, 1, 1),
    ]
    assert len(client.calls) == 2


def test_ccxt_history_fetcher_normalizes_uppercase_timeframe() -> None:
    client = FakeExchangeClient(
        pages=[
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
            ],
        ]
    )
    fetcher = CcxtHistoryFetcher(client)
    request = HistoryFetchRequest(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1D",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        limit=100,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert len(rows) == 1
    assert client.calls[0]["timeframe"] == "1d"


def test_fallback_history_fetcher_uses_secondary_when_primary_fails() -> None:
    request = HistoryFetchRequest(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        limit=2,
    )
    fallback_rows = [
        OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 0), open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0),
    ]
    fetcher = FallbackHistoryFetcher(FailingHistoryFetcher(), FakeHistoryFetcher(fallback_rows))

    rows = fetcher.fetch_ohlcv(request)

    assert rows == fallback_rows
    assert fetcher.data_source == "fake_fetcher"


def test_binance_rest_history_fetcher_paginates_without_ccxt() -> None:
    session = FakeSession(
        payloads=[
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
                _raw_row(_ms(2024, 1, 1, 1), 101.0),
            ],
            [
                _raw_row(_ms(2024, 1, 1, 2), 102.0),
            ],
        ]
    )
    fetcher = BinanceUsdMRestHistoryFetcher(session=session)
    request = HistoryFetchRequest(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 3),
        limit=2,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [
        _ms(2024, 1, 1, 0),
        _ms(2024, 1, 1, 1),
        _ms(2024, 1, 1, 2),
    ]
    assert session.calls[0]["params"]["symbol"] == "BTCUSDT"
    assert session.calls[1]["params"]["startTime"] == _ms(2024, 1, 1, 2)


def test_binance_rest_history_fetcher_pauses_between_full_pages() -> None:
    session = FakeSession(
        payloads=[
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
                _raw_row(_ms(2024, 1, 1, 1), 101.0),
            ],
            [
                _raw_row(_ms(2024, 1, 1, 2), 102.0),
            ],
        ]
    )
    sleeps: list[float] = []
    fetcher = BinanceUsdMRestHistoryFetcher(
        session=session,
        request_pause_seconds=0.75,
        sleep_fn=sleeps.append,
    )
    request = HistoryFetchRequest(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 3),
        limit=2,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [
        _ms(2024, 1, 1, 0),
        _ms(2024, 1, 1, 1),
        _ms(2024, 1, 1, 2),
    ]
    assert sleeps == [0.75]


def test_binance_rest_history_fetcher_retries_after_rate_limit() -> None:
    session = FakeSession(
        payloads=[
            FakeResponse([], status_code=429, headers={"Retry-After": "0"}),
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
            ],
        ]
    )
    sleeps: list[float] = []
    fetcher = BinanceUsdMRestHistoryFetcher(
        session=session,
        max_rate_limit_retries=2,
        retry_backoff_seconds=0.25,
        sleep_fn=sleeps.append,
    )
    request = HistoryFetchRequest(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 1),
        limit=1000,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [_ms(2024, 1, 1, 0)]
    assert len(session.calls) == 2
    assert sleeps == [0.25]


def test_binance_rest_history_fetcher_retries_after_temporary_ban() -> None:
    session = FakeSession(
        payloads=[
            FakeResponse([], status_code=418, headers={"Retry-After": "0"}),
            [
                _raw_row(_ms(2024, 1, 1, 0), 100.0),
            ],
        ]
    )
    sleeps: list[float] = []
    fetcher = BinanceUsdMRestHistoryFetcher(
        session=session,
        max_rate_limit_retries=2,
        retry_backoff_seconds=0.25,
        sleep_fn=sleeps.append,
    )
    request = HistoryFetchRequest(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 1),
        limit=1000,
    )

    rows = fetcher.fetch_ohlcv(request)

    assert [row.timestamp_ms for row in rows] == [_ms(2024, 1, 1, 0)]
    assert len(session.calls) == 2
    assert sleeps == [0.25]


def test_dataset_ingestion_uses_current_time_when_until_is_missing(tmp_path) -> None:
    rows = [
        OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 0), open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0),
        OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 1), open=100.0, high=102.0, low=99.0, close=101.0, volume=10.0),
    ]
    fetcher = FakeHistoryFetcher(rows)
    repository = FakeDatasetRepository(tmp_path)
    service = DatasetIngestionService(repository)
    request = HistoryFetchRequest(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
    )

    result = service.ingest(fetcher, request)

    assert result.dropped_open_candle is False
    assert result.snapshot.row_count == 2
    assert result.snapshot.time_range_end == _dt(2024, 1, 1, 1)


def test_dataset_ingestion_drops_last_bar_when_until_is_inside_bar(tmp_path) -> None:
    rows = [
        OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 0), open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0),
    ]
    fetcher = FakeHistoryFetcher(rows)
    repository = FakeDatasetRepository(tmp_path)
    service = DatasetIngestionService(repository)
    request = HistoryFetchRequest(
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 0, 30),
    )

    result = service.ingest(fetcher, request)

    assert result.dropped_open_candle is True
    assert result.snapshot.row_count == 0
    assert result.snapshot.time_range_start == _dt(2024, 1, 1, 0)
