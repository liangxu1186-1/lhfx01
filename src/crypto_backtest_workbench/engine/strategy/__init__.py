"""Strategy interfaces and reference implementations."""

from .base import StrategyDefinition, StrategyInput
from .ema_crossover import EMACrossoverStrategy

__all__ = ["EMACrossoverStrategy", "StrategyDefinition", "StrategyInput"]
