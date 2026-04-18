"""Repository interfaces for persisted artifacts."""

__all__ = [
    "DatasetRepository",
    "FeatureRepository",
    "RunRepository",
    "FileDatasetRepository",
    "FileFeatureRepository",
    "FileRunRepository",
]


def __getattr__(name: str):
    if name in {"DatasetRepository", "FileDatasetRepository"}:
        from crypto_backtest_workbench.storage.repositories.datasets import (
            DatasetRepository,
            FileDatasetRepository,
        )

        exports = {
            "DatasetRepository": DatasetRepository,
            "FileDatasetRepository": FileDatasetRepository,
        }
        return exports[name]

    if name in {"FeatureRepository", "FileFeatureRepository"}:
        from crypto_backtest_workbench.storage.repositories.features import (
            FeatureRepository,
            FileFeatureRepository,
        )

        exports = {
            "FeatureRepository": FeatureRepository,
            "FileFeatureRepository": FileFeatureRepository,
        }
        return exports[name]

    if name in {"RunRepository", "FileRunRepository"}:
        from crypto_backtest_workbench.storage.repositories.runs import (
            FileRunRepository,
            RunRepository,
        )

        exports = {
            "RunRepository": RunRepository,
            "FileRunRepository": FileRunRepository,
        }
        return exports[name]

    raise AttributeError(name)
