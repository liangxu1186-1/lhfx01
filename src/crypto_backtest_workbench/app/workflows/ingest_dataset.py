"""Dataset ingestion workflow assembly."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    DatasetSnapshot,
    MarketType,
    PriceType,
    now_utc,
)
from crypto_backtest_workbench.engine.data.canonicalizer import (
    drop_open_last_candle,
    ohlcv_rows_to_canonical_candles,
)
from crypto_backtest_workbench.engine.data.fetchers import (
    HistoryFetchRequest,
    HistoryFetcher,
    build_default_history_fetcher,
    normalize_timeframe,
)
from crypto_backtest_workbench.engine.data.integrity import build_integrity_report
from crypto_backtest_workbench.engine.data.service import DatasetIngestionResult, DatasetIngestionService


def ingest_dataset_workflow(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime | None = None,
    market_type: MarketType = MarketType.LINEAR_USDT_PERPETUAL,
    price_type: PriceType = PriceType.LAST,
    repository_root: str | Path | None = None,
    data_dir: str | Path | None = None,
    limit: int = 1000,
    drop_unclosed_last_candle: bool = True,
    extra_params: dict[str, object] | None = None,
    exchange_options: dict[str, object] | None = None,
    fetcher: HistoryFetcher | None = None,
) -> DatasetIngestionResult:
    """Fetch, canonicalize and persist a dataset snapshot."""

    repository = _build_dataset_repository(
        _resolve_data_dir(repository_root=repository_root, data_dir=data_dir)
    )
    request = HistoryFetchRequest(
        exchange=exchange,
        symbol=symbol,
        timeframe=normalize_timeframe(timeframe),
        market_type=market_type,
        since=since,
        until=until,
        limit=limit,
        price_type=price_type,
        extra_params=extra_params or {},
    )
    workflow_fetcher = fetcher or build_default_history_fetcher(
        exchange,
        options=exchange_options,
    )

    if drop_unclosed_last_candle:
        return DatasetIngestionService(repository).ingest(workflow_fetcher, request)

    rows = workflow_fetcher.fetch_ohlcv(request)
    candles = ohlcv_rows_to_canonical_candles(
        rows,
        exchange=request.exchange,
        symbol=request.symbol,
        market_type=request.market_type,
        timeframe=request.timeframe,
        price_type=request.price_type,
        data_source=getattr(workflow_fetcher, "data_source", "ccxt_rest"),
    )
    reference_now = request.until if request.until is not None else now_utc()
    _, has_open_last_candle = drop_open_last_candle(candles, now=reference_now)

    snapshot = _build_snapshot(
        request=request,
        row_count=len(candles),
        candles=candles,
        data_source=getattr(workflow_fetcher, "data_source", "ccxt_rest"),
    )
    integrity_report = build_integrity_report(
        snapshot.dataset_snapshot_id,
        candles,
        duplicate_bar_count=max(0, len(rows) - len(candles)),
        last_bar_closed=not has_open_last_candle,
    )

    snapshot_path = repository.save_snapshot(snapshot)
    candles_path = repository.save_candles(snapshot.dataset_snapshot_id, candles)
    integrity_report_path = repository.save_integrity_report(integrity_report)
    return DatasetIngestionResult(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        candles_path=candles_path,
        integrity_report_path=integrity_report_path,
        dropped_open_candle=False,
    )


def _resolve_data_dir(*, repository_root: str | Path | None, data_dir: str | Path | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    if repository_root is not None:
        return Path(repository_root) / "data"
    raise ValueError("Either repository_root or data_dir must be provided")


def _build_dataset_repository(base_dir: Path) -> Any:
    repository_class = _resolve_file_dataset_repository()
    return repository_class(base_dir)


def _resolve_file_dataset_repository() -> type[Any]:
    try:
        from crypto_backtest_workbench.storage.repositories.datasets import FileDatasetRepository

        return FileDatasetRepository
    except ImportError:
        module = _load_datasets_repository_module()
        return module.FileDatasetRepository


def _load_datasets_repository_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "storage" / "repositories" / "datasets.py"
    spec = importlib.util.spec_from_file_location(
        "cbw_storage_repositories_datasets",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load dataset repository module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_snapshot(
    *,
    request: HistoryFetchRequest,
    candles: list[CanonicalCandle],
    row_count: int,
    data_source: str,
) -> DatasetSnapshot:
    snapshot_id = DatasetIngestionService._build_snapshot_id(request)
    return DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source=request.exchange,
        exchange=request.exchange,
        market_type=request.market_type,
        symbol=request.symbol,
        timeframe=request.timeframe,
        time_range_start=candles[0].timestamp if candles else request.since,
        time_range_end=candles[-1].timestamp if candles else request.since,
        row_count=row_count,
        schema_version="v1",
        feature_version="pending",
        storage_uri=f"datasets/{snapshot_id}",
        data_source=data_source,
        price_type=request.price_type,
    )
