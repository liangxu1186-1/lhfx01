"""Storage helpers."""

__all__ = [
    "DatasetRepository",
    "FeatureRepository",
    "RunRepository",
    "FileDatasetRepository",
    "FileFeatureRepository",
    "FileRunRepository",
    "artifact_uri",
]


def __getattr__(name: str):
    if name == "artifact_uri":
        from crypto_backtest_workbench.storage.paths import artifact_uri

        return artifact_uri

    if name in {
        "DatasetRepository",
        "FeatureRepository",
        "RunRepository",
        "FileDatasetRepository",
        "FileFeatureRepository",
        "FileRunRepository",
    }:
        from crypto_backtest_workbench.storage.repositories import __getattr__ as repositories_getattr

        return repositories_getattr(name)

    raise AttributeError(name)
