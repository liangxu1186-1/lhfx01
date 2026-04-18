"""Simple feature cache registry for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_backtest_workbench.domain.models import FeatureArtifact


@dataclass(slots=True)
class FeatureCacheRegistry:
    """In-memory registry used by Phase 1 orchestration tests and scaffolding."""

    artifacts_by_key: dict[str, FeatureArtifact] = field(default_factory=dict)

    def has(self, feature_cache_key: str) -> bool:
        return feature_cache_key in self.artifacts_by_key

    def get(self, feature_cache_key: str) -> FeatureArtifact | None:
        return self.artifacts_by_key.get(feature_cache_key)

    def register(self, artifact: FeatureArtifact) -> FeatureArtifact:
        existing = self.artifacts_by_key.get(artifact.feature_cache_key)
        if existing is not None:
            return existing
        self.artifacts_by_key[artifact.feature_cache_key] = artifact
        return artifact

