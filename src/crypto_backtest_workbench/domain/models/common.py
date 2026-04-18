"""Shared enums and helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


def now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class MarketType(StrEnum):
    LINEAR_USDT_PERPETUAL = "linear_usdt_perpetual"


class PriceType(StrEnum):
    LAST = "last"
    MARK = "mark"
    INDEX = "index"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SignalAction(StrEnum):
    OPEN = "open"
    CLOSE = "close"
    REVERSE = "reverse"
    HOLD = "hold"


class ValidationTargetType(StrEnum):
    DATASET_SNAPSHOT = "dataset_snapshot"
    DATASET_BUNDLE = "dataset_bundle"


class WarningType(StrEnum):
    DATA_WARNING = "data_warning"
    EXECUTION_WARNING = "execution_warning"
    ANALYTICS_WARNING = "analytics_warning"


class FailureCode(StrEnum):
    DATA_INVALID = "DATA_INVALID"
    DATA_INSUFFICIENT_WARMUP = "DATA_INSUFFICIENT_WARMUP"
    CONFIG_INVALID = "CONFIG_INVALID"
    ORDER_REJECTED_BY_CONSTRAINT = "ORDER_REJECTED_BY_CONSTRAINT"
    ENGINE_RUNTIME_ERROR = "ENGINE_RUNTIME_ERROR"
    ANALYTICS_FAILED = "ANALYTICS_FAILED"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SearchType(StrEnum):
    GRID = "grid"
    RANDOM = "random"


class SeedPolicy(StrEnum):
    FIXED = "FIXED"
    PER_RUN_RANDOM = "PER_RUN_RANDOM"
    GLOBAL_RANDOM = "GLOBAL_RANDOM"


class RejectReasonCode(StrEnum):
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    MIN_NOTIONAL = "MIN_NOTIONAL"
    PRECISION_VIOLATION = "PRECISION_VIOLATION"
    INVALID_QTY = "INVALID_QTY"

