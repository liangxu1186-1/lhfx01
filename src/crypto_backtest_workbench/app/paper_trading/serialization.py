"""JSON serialization helpers for paper trading."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum


def json_ready(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [json_ready(inner) for inner in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value

