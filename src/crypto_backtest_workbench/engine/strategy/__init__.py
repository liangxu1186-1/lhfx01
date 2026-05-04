"""Strategy interfaces and reference implementations."""

from .base import StrategyDefinition, StrategyInput
from .ema_crossover import EMACrossoverStrategy
from .ema_pullback_atr import EMAPullbackATRStrategy

__all__ = ["EMACrossoverStrategy", "EMAPullbackATRStrategy", "StrategyDefinition", "StrategyInput"]
