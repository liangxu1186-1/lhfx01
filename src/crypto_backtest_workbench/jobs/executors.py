"""Adapters that connect prepared single-run inputs to LocalTaskRunner."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.domain.models import CanonicalCandle, FailureCode, SignalIntent, ValidationSplit
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs.runner import SingleRunTaskExecutor, TaskExecutionError
from crypto_backtest_workbench.jobs.single_run import (
    SingleRunOrchestrator,
    SingleRunRequest,
    SingleRunResult,
)
from crypto_backtest_workbench.jobs.task_models import SingleRunTaskPayload


@dataclass(slots=True)
class PreparedSingleRunInput:
    payload: SingleRunTaskPayload
    request: SingleRunRequest
    candles: list[CanonicalCandle]
    signals: list[SignalIntent]
    constraints: ExecutionConstraints
    validation_split: ValidationSplit | None = None


class PreparedSingleRunExecutor(SingleRunTaskExecutor[SingleRunResult]):
    """Resolve a submitted payload into a prepared orchestrator input."""

    def __init__(
        self,
        orchestrator: SingleRunOrchestrator,
        prepared_inputs: dict[str, PreparedSingleRunInput],
    ) -> None:
        self.orchestrator = orchestrator
        self.prepared_inputs = prepared_inputs

    def execute_single_run(self, payload: SingleRunTaskPayload) -> SingleRunResult:
        prepared = self.prepared_inputs.get(payload.run_id)
        if prepared is None:
            raise TaskExecutionError(
                failure_code=FailureCode.CONFIG_INVALID,
                failure_stage="prepared_single_run_executor",
                failure_message=f"missing prepared single-run input for {payload.run_id}",
            )

        return self.orchestrator.execute(
            request=prepared.request,
            candles=prepared.candles,
            signals=prepared.signals,
            constraints=prepared.constraints,
            validation_split=prepared.validation_split,
        )
