"""Artifact path helpers."""

from __future__ import annotations

from pathlib import Path


def artifact_uri(base_dir: Path, *parts: str, suffix: str | None = None) -> str:
    target = base_dir.joinpath(*parts)
    if suffix is not None:
        target = target.with_suffix(suffix)
    return str(target)

