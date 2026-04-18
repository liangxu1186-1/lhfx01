"""Repository interfaces for persisted artifacts."""

from crypto_backtest_workbench.storage.repositories.datasets import (
    DatasetRepository,
    FileDatasetRepository,
)

__all__ = ["DatasetRepository", "FileDatasetRepository"]

