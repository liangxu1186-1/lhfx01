"""Execution layer."""

from crypto_backtest_workbench.engine.execution.policies import DEFAULT_EXECUTION_POLICY
from crypto_backtest_workbench.engine.execution.simulator import (
    ExecutionConstraints,
    ExecutionResult,
    simulate_signals,
)

__all__ = [
    "DEFAULT_EXECUTION_POLICY",
    "ExecutionConstraints",
    "ExecutionResult",
    "simulate_signals",
]
