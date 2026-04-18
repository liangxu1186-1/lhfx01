"""Utilities for loading precomputed strategy features."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


@dataclass(slots=True, frozen=True)
class FeatureRow:
    timestamp: datetime
    values: dict[str, float | None]


def load_feature_rows(
    features_uri: str,
    *,
    required_columns: tuple[str, ...],
) -> list[FeatureRow]:
    """Load precomputed feature rows from a local CSV file."""
    path = _resolve_features_path(features_uri)
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Unsupported feature file format: {path.suffix or '<none>'}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Feature file is missing a header row.")

        missing = [column for column in required_columns if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"Feature file is missing required columns: {', '.join(missing)}")

        rows: list[FeatureRow] = []
        for line_number, row in enumerate(reader, start=2):
            timestamp_value = row.get("timestamp")
            if not timestamp_value:
                raise ValueError(f"Missing timestamp at line {line_number}.")

            try:
                timestamp = _parse_timestamp(timestamp_value)
                values = {
                    column: _parse_optional_float(row[column]) for column in required_columns if column != "timestamp"
                }
            except ValueError as exc:
                raise ValueError(
                    f"Invalid feature value at line {line_number}: {exc}"
                ) from exc

            rows.append(FeatureRow(timestamp=timestamp, values=values))

    rows.sort(key=lambda item: item.timestamp)
    return rows


def _resolve_features_path(features_uri: str) -> Path:
    parsed = urlparse(features_uri)
    if parsed.scheme in ("", "file"):
        candidate = parsed.path if parsed.scheme == "file" else features_uri
        return Path(candidate).expanduser().resolve()

    raise ValueError(f"Unsupported features URI scheme: {parsed.scheme}")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _parse_optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
