"""Application workflows."""

from crypto_backtest_workbench.app.workflows.parameter_experiment_batch import (
    ParameterExperimentBatchRequest,
    ParameterExperimentBatchWorkflowResult,
    build_parameter_experiment_batch,
    run_parameter_experiment_batch_workflow,
)
from crypto_backtest_workbench.app.workflows.parameter_experiment_task import (
    ParameterExperimentTaskRequest,
    ParameterExperimentTaskWorkflowResult,
    build_parameter_experiment_task,
    run_parameter_experiment_task_workflow,
)
from crypto_backtest_workbench.app.workflows.execution_verification import (
    EXECUTION_VERIFICATION_MODEL_VERSION,
    EXECUTION_VERIFICATION_RUN_TYPE,
    ExecutionVerificationRequest,
    ExecutionVerificationResult,
    is_execution_verification_manifest,
    run_execution_verification_workflow,
)
from crypto_backtest_workbench.app.workflows.run_backtest import (
    RunBacktestWorkflowRequest,
    RunBacktestWorkflowResult,
    run_backtest_workflow,
)
from crypto_backtest_workbench.app.workflows.run_backtest_task import (
    RunBacktestTaskOutput,
    RunBacktestTaskWorkflowResult,
    run_backtest_task_workflow,
)


def ingest_dataset_workflow(*args, **kwargs):
    from crypto_backtest_workbench.app.workflows.ingest_dataset import ingest_dataset_workflow as _ingest_dataset_workflow

    return _ingest_dataset_workflow(*args, **kwargs)


__all__ = [
    "ParameterExperimentBatchRequest",
    "ParameterExperimentBatchWorkflowResult",
    "ParameterExperimentTaskRequest",
    "ParameterExperimentTaskWorkflowResult",
    "EXECUTION_VERIFICATION_MODEL_VERSION",
    "EXECUTION_VERIFICATION_RUN_TYPE",
    "ExecutionVerificationRequest",
    "ExecutionVerificationResult",
    "RunBacktestTaskOutput",
    "RunBacktestTaskWorkflowResult",
    "RunBacktestWorkflowRequest",
    "RunBacktestWorkflowResult",
    "build_parameter_experiment_batch",
    "build_parameter_experiment_task",
    "ingest_dataset_workflow",
    "is_execution_verification_manifest",
    "run_execution_verification_workflow",
    "run_parameter_experiment_batch_workflow",
    "run_parameter_experiment_task_workflow",
    "run_backtest_task_workflow",
    "run_backtest_workflow",
]
