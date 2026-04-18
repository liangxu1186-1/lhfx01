from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from crypto_backtest_workbench.app.workflows import ingest_dataset_workflow
from crypto_backtest_workbench.domain.models import MarketType
from crypto_backtest_workbench.engine.data.fetchers import HistoryFetchRequest, OhlcvRow


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(_dt(year, month, day, hour, minute).timestamp() * 1000)


class FakeHistoryFetcher:
    def __init__(self, rows: list[OhlcvRow]) -> None:
        self.rows = rows
        self.requests: list[HistoryFetchRequest] = []

    def fetch_ohlcv(self, request: HistoryFetchRequest) -> list[OhlcvRow]:
        self.requests.append(request)
        return list(self.rows)


def test_ingest_dataset_workflow_uses_repository_root_and_drops_open_last_candle(tmp_path: Path) -> None:
    fetcher = FakeHistoryFetcher(
        [
            OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 0), open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0),
            OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 1), open=100.0, high=102.0, low=99.0, close=101.0, volume=12.0),
        ]
    )

    result = ingest_dataset_workflow(
        repository_root=tmp_path,
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 1, 30),
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        drop_unclosed_last_candle=True,
        fetcher=fetcher,
    )

    assert result.dropped_open_candle is True
    assert result.snapshot.row_count == 1
    assert result.snapshot_path == tmp_path / "data" / "datasets" / result.snapshot.dataset_snapshot_id / "snapshot.json"
    assert result.candles_path.exists()
    assert result.integrity_report_path.exists()
    assert len(fetcher.requests) == 1

    with result.candles_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["timestamp"] == _dt(2024, 1, 1, 0).isoformat()


def test_ingest_dataset_workflow_can_keep_open_last_candle_when_disabled(tmp_path: Path) -> None:
    fetcher = FakeHistoryFetcher(
        [
            OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 0), open=99.0, high=101.0, low=98.0, close=100.0, volume=10.0),
            OhlcvRow(timestamp_ms=_ms(2024, 1, 1, 1), open=100.0, high=102.0, low=99.0, close=101.0, volume=12.0),
        ]
    )

    result = ingest_dataset_workflow(
        data_dir=tmp_path / "custom-data",
        exchange="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=_dt(2024, 1, 1, 0),
        until=_dt(2024, 1, 1, 1, 30),
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        drop_unclosed_last_candle=False,
        fetcher=fetcher,
    )

    assert result.dropped_open_candle is False
    assert result.snapshot.row_count == 2
    assert result.snapshot.time_range_end == _dt(2024, 1, 1, 1)

    with result.candles_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2

    with result.integrity_report_path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["last_bar_closed"] is False
