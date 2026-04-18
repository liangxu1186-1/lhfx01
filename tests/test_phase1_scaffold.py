from __future__ import annotations

import json

import pytest

from crypto_backtest_workbench.cli import main, scaffold_layout
from crypto_backtest_workbench.domain.models.features import (
    FeatureArtifact,
    FeatureCacheKey,
)
from crypto_backtest_workbench.domain.models.run import RunManifest
from crypto_backtest_workbench.engine.execution.policies import (
    DEFAULT_EXECUTION_POLICY,
)


def build_manifest(**overrides: object) -> RunManifest:
    payload: dict[str, object] = {
        "run_id": "run-001",
        "dataset_snapshot_id": "snapshot-001",
        "strategy_version": "strategy-v1",
        "engine_version": "engine-v1",
        "execution_policy_id": "exec-v1",
        "metric_policy_id": "metric-v1",
        "feature_artifact_id": "feature-001",
        "validation_split_id": "split-001",
        "fee_model_version": "fee-v1",
        "slippage_model_version": "slippage-v1",
        "fee_model_params_json": {"rate": 0.001},
        "slippage_model_params_json": {"bps": 5},
        "benchmark_config_json": {"benchmark_type": "buy_and_hold"},
        "resolved_config_json": {"seed": 7},
        "seed": 7,
    }
    payload.update(overrides)
    return RunManifest(**payload)


def test_feature_cache_key_as_string_uses_expected_layout() -> None:
    key = FeatureCacheKey(
        dataset_snapshot_id="snapshot-001",
        feature_version="ema-v2",
        input_price_field="close",
        feature_params_hash="abc123",
        warmup_bars=42,
    )

    assert key.as_string() == "snapshot-001:ema-v2:close:abc123:42"


def test_feature_artifact_from_cache_key_populates_cache_key_string() -> None:
    artifact = FeatureArtifact.from_cache_key(
        feature_artifact_id="feature-001",
        dataset_snapshot_id="snapshot-001",
        feature_version="ema-v2",
        feature_params_json={"window": 20},
        feature_params_hash="abc123",
        input_price_field="close",
        warmup_bars=42,
        storage_uri="s3://artifacts/feature-001.parquet",
        depends_on=("dataset-raw",),
    )

    assert artifact.feature_cache_key == "snapshot-001:ema-v2:close:abc123:42"
    assert artifact.depends_on == ("dataset-raw",)
    assert artifact.storage_uri == "s3://artifacts/feature-001.parquet"


def test_run_manifest_validate_required_fields_accepts_complete_manifest() -> None:
    manifest = build_manifest()

    manifest.validate_required_fields()


def test_run_manifest_validate_required_fields_reports_sorted_missing_fields() -> None:
    manifest = build_manifest(
        strategy_version="",
        execution_policy_id="",
        fee_model_version="",
    )

    with pytest.raises(ValueError) as exc_info:
        manifest.validate_required_fields()

    assert (
        str(exc_info.value)
        == "RunManifest missing required fields: execution_policy_id, fee_model_version, strategy_version"
    )


def test_default_execution_policy_fields_match_phase1_defaults() -> None:
    assert DEFAULT_EXECUTION_POLICY.execution_policy_id == "signal_on_bar_close_fill_on_next_bar_open"
    assert DEFAULT_EXECUTION_POLICY.signal_timing == "bar_close"
    assert DEFAULT_EXECUTION_POLICY.fill_timing == "next_bar_open"
    assert DEFAULT_EXECUTION_POLICY.price_field_used == "open"
    assert DEFAULT_EXECUTION_POLICY.allow_same_bar_exit is False
    assert DEFAULT_EXECUTION_POLICY.version == "v1"


def test_cli_scaffold_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["cbw", "scaffold", "--json"])

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == scaffold_layout()
