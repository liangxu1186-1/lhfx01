"""Shared feature pipeline records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class FeatureRow:
    timestamp: datetime
    symbol: str
    values: dict[str, float | None]
