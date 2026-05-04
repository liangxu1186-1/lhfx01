"""Feature pipeline for Phase 1."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Sequence

from crypto_backtest_workbench.domain.models import CanonicalCandle, FeatureArtifact, FeatureSpec
from crypto_backtest_workbench.engine.features.cache import FeatureCacheRegistry
from crypto_backtest_workbench.engine.features.indicators import compute_adx, compute_atr, compute_ema, compute_rsi
from crypto_backtest_workbench.engine.features.records import FeatureRow
from crypto_backtest_workbench.storage.repositories.features import FeatureRepository


PIPELINE_VERSION = "feature-pipeline-v2"
FEATURE_IMPLEMENTATION_VERSIONS: dict[str, str] = {
    "ema": "ema-v1",
    "rsi": "rsi-v1",
    "atr": "atr-v1",
    "adx": "adx-v1",
}


class FeaturePipeline:
    """Materialize reusable feature artifacts from canonical candles."""

    def __init__(
        self,
        repository: FeatureRepository,
        *,
        cache_registry: FeatureCacheRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.cache_registry = cache_registry

    def materialize(
        self,
        *,
        dataset_snapshot_id: str,
        candles: Sequence[CanonicalCandle],
        specs: Sequence[FeatureSpec],
        depends_on: tuple[str, ...] = (),
    ) -> FeatureArtifact:
        if not candles:
            raise ValueError("FeaturePipeline requires at least one canonical candle")
        if not specs:
            raise ValueError("FeaturePipeline requires at least one feature spec")

        input_price_field = self._resolve_input_price_field(specs)
        feature_params_json = {"features": [_spec_to_json(spec) for spec in specs]}
        feature_params_hash = _stable_digest(feature_params_json)
        feature_version = self._build_feature_version(specs)
        warmup_bars = max(_effective_warmup(spec) for spec in specs)
        feature_cache_key = (
            f"{dataset_snapshot_id}:{feature_version}:{input_price_field}:{feature_params_hash}:{warmup_bars}"
        )

        artifact = self._lookup_cached_artifact(feature_cache_key)
        if artifact is not None:
            return artifact

        feature_artifact_id = f"feature-{_stable_digest(feature_cache_key)[:16]}"
        storage_uri = self.repository.build_storage_uri(feature_artifact_id)
        artifact = FeatureArtifact.from_cache_key(
            feature_artifact_id=feature_artifact_id,
            dataset_snapshot_id=dataset_snapshot_id,
            feature_version=feature_version,
            feature_params_json=feature_params_json,
            feature_params_hash=feature_params_hash,
            input_price_field=input_price_field,
            warmup_bars=warmup_bars,
            storage_uri=storage_uri,
            depends_on=depends_on,
        )

        rows = self._build_rows(candles=candles, specs=specs)
        column_names = ("open", "high", "low", "close", *tuple(_feature_column_name(spec) for spec in specs))
        self.repository.save_artifact(artifact)
        self.repository.save_feature_rows(
            feature_artifact_id=artifact.feature_artifact_id,
            feature_names=column_names,
            rows=rows,
        )
        if self.cache_registry is not None:
            self.cache_registry.register(artifact)
        return artifact

    def _lookup_cached_artifact(self, feature_cache_key: str) -> FeatureArtifact | None:
        if self.cache_registry is not None:
            cached = self.cache_registry.get(feature_cache_key)
            if cached is not None:
                return cached

        cached = self.repository.get_artifact(feature_cache_key)
        if cached is not None and self.cache_registry is not None:
            self.cache_registry.register(cached)
        return cached

    def _build_feature_version(self, specs: Sequence[FeatureSpec]) -> str:
        versions = []
        for spec in specs:
            version = FEATURE_IMPLEMENTATION_VERSIONS.get(spec.name)
            if version is None:
                raise ValueError(f"Unsupported feature spec: {spec.name}")
            versions.append(version)
        return "__".join([PIPELINE_VERSION, *versions])

    def _resolve_input_price_field(self, specs: Sequence[FeatureSpec]) -> str:
        price_fields = {spec.input_price_field for spec in specs}
        if len(price_fields) != 1:
            raise ValueError("Phase 1 feature artifacts require a single shared input price field")
        return next(iter(price_fields))

    def _build_rows(
        self,
        *,
        candles: Sequence[CanonicalCandle],
        specs: Sequence[FeatureSpec],
    ) -> list[FeatureRow]:
        prices_by_field = self._extract_prices_by_field(candles, specs)
        computed_features = {
            _feature_column_name(spec): _compute_feature_series(spec, prices_by_field[spec.input_price_field], candles)
            for spec in specs
        }

        rows: list[FeatureRow] = []
        for index, candle in enumerate(candles):
            values = {
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            }
            values.update({column_name: series[index] for column_name, series in computed_features.items()})
            rows.append(
                FeatureRow(
                    timestamp=candle.timestamp,
                    symbol=candle.symbol,
                    values=values,
                )
            )
        return rows

    def _extract_prices_by_field(
        self,
        candles: Sequence[CanonicalCandle],
        specs: Iterable[FeatureSpec],
    ) -> dict[str, list[float]]:
        price_fields = {spec.input_price_field for spec in specs}
        extracted: dict[str, list[float]] = {}
        for price_field in price_fields:
            extracted[price_field] = [float(getattr(candle, price_field)) for candle in candles]
        return extracted


def _compute_feature_series(
    spec: FeatureSpec,
    prices: Sequence[float],
    candles: Sequence[CanonicalCandle],
) -> list[float | None]:
    if spec.name == "ema":
        window = _require_positive_int(spec, "window")
        return compute_ema(prices, window)
    if spec.name == "rsi":
        window = _require_positive_int(spec, "window")
        return compute_rsi(prices, window)
    if spec.name == "atr":
        window = _require_positive_int(spec, "window")
        return compute_atr(candles, window)
    if spec.name == "adx":
        window = _require_positive_int(spec, "window")
        return compute_adx(candles, window)
    raise ValueError(f"Unsupported feature spec: {spec.name}")


def _effective_warmup(spec: FeatureSpec) -> int:
    if spec.name in {"ema", "rsi", "atr", "adx"}:
        window = _require_positive_int(spec, "window")
        intrinsic = max(window, spec.warmup_bars)
        return intrinsic
    raise ValueError(f"Unsupported feature spec: {spec.name}")


def _feature_column_name(spec: FeatureSpec) -> str:
    if spec.name in {"ema", "rsi"}:
        window = _require_positive_int(spec, "window")
        return f"{spec.name}_{spec.input_price_field}_{window}"
    if spec.name in {"atr", "adx"}:
        window = _require_positive_int(spec, "window")
        return f"{spec.name}_{window}"
    raise ValueError(f"Unsupported feature spec: {spec.name}")


def _require_positive_int(spec: FeatureSpec, field_name: str) -> int:
    raw_value = spec.params.get(field_name)
    if not isinstance(raw_value, int) or raw_value <= 0:
        raise ValueError(f"Feature spec '{spec.name}' requires a positive integer '{field_name}'")
    return raw_value


def _spec_to_json(spec: FeatureSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "params": dict(sorted(spec.params.items())),
        "input_price_field": spec.input_price_field,
        "warmup_bars": spec.warmup_bars,
    }


def _stable_digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
