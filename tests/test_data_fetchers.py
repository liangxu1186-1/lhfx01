from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json

from crypto_backtest_workbench.domain.models import MarketType
from crypto_backtest_workbench.engine.data.fetchers import (
    CcxtHistoryFetcher,
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

    def fetch_ohlcv(self, request: HistoryFetchRequest) -> list[OhlcvRow]:
        return list(self._rows)


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
