"""Dataset and validation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models.common import (
    MarketType,
    PriceType,
    ValidationTargetType,
    now_utc,
)


@dataclass(slots=True, frozen=True)
class CanonicalCandle:
    timestamp: datetime
    symbol: str
    exchange: str
    market_type: MarketType
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    price_type: PriceType = PriceType.LAST
    data_source: str = "ccxt_rest"


@dataclass(slots=True)
class DatasetSnapshot:
    dataset_snapshot_id: str
    source: str
    exchange: str
    market_type: MarketType
    symbol: str
    timeframe: str
    time_range_start: datetime
    time_range_end: datetime
    row_count: int
    schema_version: str
    feature_version: str
    storage_uri: str
    data_source: str
    price_type: PriceType
    created_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class DatasetBundle:
    dataset_bundle_id: str
    dataset_snapshot_ids: tuple[str, ...]
    exchange: str
    market_type: MarketType
    timeframe: str
    symbol_list: tuple[str, ...]
    time_range_start: datetime
    time_range_end: datetime
    data_source: str
    price_type: PriceType
    created_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class ValidationSplit:
    validation_split_id: str
    target_type: ValidationTargetType
    target_id: str
    warmup_bars: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    is_start_inclusive: bool = True
    is_end_exclusive: bool = True
    oos_start_inclusive: bool = True
    oos_end_exclusive: bool = True
    feature_cutoff_rule: str = "window_must_be_full"
    split_type: str = "single_is_oos"


@dataclass(slots=True)
class DataIntegrityReport:
    dataset_snapshot_id: str
    missing_bar_count: int = 0
    duplicate_bar_count: int = 0
    gap_segments: tuple[tuple[datetime, datetime], ...] = ()
    last_bar_closed: bool = True
    source_consistency_flag: bool = True

