"""Strategy interface definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from crypto_backtest_workbench.domain.models import FeatureSpec, SignalIntent


@dataclass(slots=True)
class StrategyInput:
    run_id: str
    symbol: str
    timeframe: str
    feature_artifact_id: str
    features_uri: str
    config: dict[str, object] = field(default_factory=dict)


class StrategyDefinition(ABC):
    """Minimal strategy contract for Phase 1."""

    name: str
    version: str

    @abstractmethod
    def feature_specs(self) -> tuple[FeatureSpec, ...]:
        """Declare the feature columns needed by this strategy."""

    @abstractmethod
    def generate_signals(self, data: StrategyInput) -> list[SignalIntent]:
        """Generate signals using precomputed features only."""

