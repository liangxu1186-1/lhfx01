"""Helpers for materializing ValidationSplit views."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.domain.models import CanonicalCandle, ValidationSplit


@dataclass(slots=True, frozen=True)
class ValidationSegment:
    name: str
    warmup_candles: tuple[CanonicalCandle, ...]
    analysis_candles: tuple[CanonicalCandle, ...]
    window_candles: tuple[CanonicalCandle, ...]
    warmup_complete: bool


@dataclass(slots=True, frozen=True)
class ValidationView:
    is_segment: ValidationSegment
    oos_segment: ValidationSegment


def build_validation_view(
    *,
    candles: list[CanonicalCandle],
    split: ValidationSplit,
) -> ValidationView:
    ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
    is_segment = _build_segment(
        name="is",
        candles=ordered,
        start=split.is_start,
        end=split.is_end,
        start_inclusive=split.is_start_inclusive,
        end_exclusive=split.is_end_exclusive,
        warmup_bars=split.warmup_bars,
    )
    oos_segment = _build_segment(
        name="oos",
        candles=ordered,
        start=split.oos_start,
        end=split.oos_end,
        start_inclusive=split.oos_start_inclusive,
        end_exclusive=split.oos_end_exclusive,
        warmup_bars=split.warmup_bars,
    )
    return ValidationView(is_segment=is_segment, oos_segment=oos_segment)


def _build_segment(
    *,
    name: str,
    candles: tuple[CanonicalCandle, ...],
    start,
    end,
    start_inclusive: bool,
    end_exclusive: bool,
    warmup_bars: int,
) -> ValidationSegment:
    analysis_indices = tuple(
        index
        for index, candle in enumerate(candles)
        if _is_within_window(
            candle=candle,
            start=start,
            end=end,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
        )
    )

    if not analysis_indices:
        return ValidationSegment(
            name=name,
            warmup_candles=(),
            analysis_candles=(),
            window_candles=(),
            warmup_complete=warmup_bars == 0,
        )

    first_index = analysis_indices[0]
    warmup_start = max(0, first_index - warmup_bars)
    warmup_candles = candles[warmup_start:first_index]
    analysis_candles = tuple(candles[index] for index in analysis_indices)
    return ValidationSegment(
        name=name,
        warmup_candles=warmup_candles,
        analysis_candles=analysis_candles,
        window_candles=warmup_candles + analysis_candles,
        warmup_complete=len(warmup_candles) == warmup_bars,
    )


def _is_within_window(
    *,
    candle: CanonicalCandle,
    start,
    end,
    start_inclusive: bool,
    end_exclusive: bool,
) -> bool:
    if start_inclusive:
        starts_after_boundary = candle.timestamp >= start
    else:
        starts_after_boundary = candle.timestamp > start

    if end_exclusive:
        ends_before_boundary = candle.timestamp < end
    else:
        ends_before_boundary = candle.timestamp <= end

    return starts_after_boundary and ends_before_boundary
