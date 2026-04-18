"""Dataset persistence for Phase 1."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import CanonicalCandle, DataIntegrityReport, DatasetSnapshot


class DatasetRepository(Protocol):
    """Persistence contract for dataset artifacts."""

    def save_snapshot(self, snapshot: DatasetSnapshot) -> Path:
        """Persist dataset snapshot metadata."""

    def save_candles(self, snapshot_id: str, candles: list[CanonicalCandle]) -> Path:
        """Persist canonical candles."""

    def save_integrity_report(self, report: DataIntegrityReport) -> Path:
        """Persist data integrity report."""


class FileDatasetRepository:
    """Filesystem-backed repository for Phase 1 scaffolding."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        return self.base_dir / "datasets" / snapshot_id

    def save_snapshot(self, snapshot: DatasetSnapshot) -> Path:
        directory = self._snapshot_dir(snapshot.dataset_snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "snapshot.json"
        path.write_text(
            json.dumps(_json_ready(asdict(snapshot)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def save_candles(self, snapshot_id: str, candles: list[CanonicalCandle]) -> Path:
        directory = self._snapshot_dir(snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "canonical_candles.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
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
                        "market_type": candle.market_type,
                        "timeframe": candle.timeframe,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                        "price_type": candle.price_type,
                        "data_source": candle.data_source,
                    }
                )
        return path

    def save_integrity_report(self, report: DataIntegrityReport) -> Path:
        directory = self._snapshot_dir(report.dataset_snapshot_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "integrity_report.json"
        path.write_text(
            json.dumps(_json_ready(asdict(report)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value

