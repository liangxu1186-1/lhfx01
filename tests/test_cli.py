from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crypto_backtest_workbench import cli
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
    ValidationTargetType,
)


def test_parse_datetime_adds_utc_when_missing_timezone() -> None:
    parsed = cli._parse_datetime("2024-01-01T00:00:00")

    assert parsed == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def test_parse_json_object_arg_returns_object() -> None:
    parsed = cli._parse_json_object_arg('{"options":{"defaultType":"future"}}', field_name="--exchange-options-json")

    assert parsed == {"options": {"defaultType": "future"}}


def test_parse_json_object_arg_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        cli._parse_json_object_arg('["not","an","object"]', field_name="--extra-params-json")


def test_handle_ingest_passes_exchange_options_and_extra_params(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_ingest_dataset_workflow(**kwargs):
        recorded.update(kwargs)

        class _Snapshot:
            dataset_snapshot_id = "snapshot-001"
            row_count = 10

        class _Result:
            snapshot = _Snapshot()
            snapshot_path = "/tmp/snapshot.json"
            candles_path = "/tmp/candles.csv"
            integrity_report_path = "/tmp/integrity.json"
            dropped_open_candle = True

        return _Result()

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.workflows.ingest_dataset_workflow",
        fake_ingest_dataset_workflow,
    )

    args = argparse.Namespace(
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since="2024-01-01T00:00:00+00:00",
        until="2024-01-02T00:00:00+00:00",
        repository_root=".",
        data_dir=None,
        market_type="linear_usdt_perpetual",
        price_type="last",
        limit=500,
        exchange_options_json='{"options":{"defaultType":"future"}}',
        extra_params_json='{"foo":"bar"}',
        keep_open_last_candle=False,
    )

    exit_code = cli._handle_ingest(args)

    assert exit_code == 0
    assert recorded["exchange_options"] == {"options": {"defaultType": "future"}}
    assert recorded["extra_params"] == {"foo": "bar"}


def test_run_command_returns_json_error_and_exit_code_1(capsys) -> None:
    def failing_handler(_args: argparse.Namespace) -> int:
        raise RuntimeError("boom")

    exit_code = cli._run_command(failing_handler, argparse.Namespace())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"type": "RuntimeError"' in captured.out
    assert '"message": "boom"' in captured.out


def test_build_validation_split_returns_none_when_no_boundaries() -> None:
    split = cli._build_validation_split(
        args=argparse.Namespace(
            validation_split_id="validation:cli",
            warmup_bars=0,
            is_start=None,
            is_end=None,
            oos_start=None,
            oos_end=None,
        ),
        snapshot=_snapshot(),
    )

    assert split is None


def test_build_validation_split_builds_dataset_snapshot_split() -> None:
    split = cli._build_validation_split(
        args=argparse.Namespace(
            validation_split_id="split-001",
            warmup_bars=12,
            is_start="2024-01-01T00:00:00+00:00",
            is_end="2024-01-10T00:00:00+00:00",
            oos_start="2024-01-10T00:00:00+00:00",
            oos_end="2024-01-20T00:00:00+00:00",
        ),
        snapshot=_snapshot(),
    )

    assert split is not None
    assert split.validation_split_id == "split-001"
    assert split.target_type is ValidationTargetType.DATASET_SNAPSHOT
    assert split.target_id == "snapshot-001"
    assert split.warmup_bars == 12


def test_build_validation_split_requires_full_boundary_set() -> None:
    with pytest.raises(ValueError, match="Validation split requires all of"):
        cli._build_validation_split(
            args=argparse.Namespace(
                validation_split_id="split-001",
                warmup_bars=0,
                is_start="2024-01-01T00:00:00+00:00",
                is_end=None,
                oos_start=None,
                oos_end=None,
            ),
            snapshot=_snapshot(),
        )


def test_handle_run_ema_passes_validation_split(monkeypatch, tmp_path) -> None:
    recorded: dict[str, object] = {}
    captured_payload: dict[str, object] = {}

    class _FeatureArtifact:
        feature_artifact_id = "feature-001"

    class _Execution:
        orders = [object(), object()]
        fills = [object()]
        warnings = [object()]

    class _Metrics:
        def as_dict(self):
            return {"trade_count": 1}

    class _Run:
        run_id = "run-001"
        validation_split_id = "split-001"

    class _SingleRunResult:
        run = _Run()
        metrics = _Metrics()
        benchmark_output = None
        execution = _Execution()

    class _WorkflowResult:
        feature_artifact = _FeatureArtifact()
        signals = [object()]
        single_run_result = _SingleRunResult()

    class _Task:
        task_id = "single-run:run-001"
        status = type("_Status", (), {"value": "success"})()
        failure_code = None
        failure_stage = None
        failure_message = None

    class _TaskOutput:
        workflow_result = _WorkflowResult()
        persisted_paths = {"run": "/tmp/run.json"}

    class _TaskWorkflowResult:
        task = _Task()
        output = _TaskOutput()

    def fake_run_backtest_task_workflow(**kwargs):
        captured_payload.update(kwargs)
        recorded["request"] = kwargs["request"]
        return _TaskWorkflowResult()

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.workflows.run_backtest_task_workflow",
        fake_run_backtest_task_workflow,
    )

    data_dir = tmp_path / "data"
    snapshot_dir = data_dir / "datasets" / "snapshot-001"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot.json").write_text(
        """
        {
          "dataset_snapshot_id": "snapshot-001",
          "source": "binance",
          "exchange": "binance",
          "market_type": "linear_usdt_perpetual",
          "symbol": "BTC/USDT:USDT",
          "timeframe": "1h",
          "time_range_start": "2024-01-01T00:00:00+00:00",
          "time_range_end": "2024-01-20T00:00:00+00:00",
          "row_count": 100,
          "schema_version": "v1",
          "feature_version": "pending",
          "storage_uri": "datasets/snapshot-001",
          "created_at": "2024-01-20T00:00:00+00:00",
          "data_source": "fixture",
          "price_type": "last"
        }
        """.strip(),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        snapshot_id="snapshot-001",
        run_id="run-001",
        repository_root=".",
        data_dir=str(data_dir),
        fast_period=2,
        slow_period=3,
        qty_policy_ref="fixed_1",
        qty=1.0,
        initial_cash=1000.0,
        leverage=1.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        min_notional=0.0,
        validation_split_id="split-001",
        warmup_bars=5,
        is_start="2024-01-01T00:00:00+00:00",
        is_end="2024-01-10T00:00:00+00:00",
        oos_start="2024-01-10T00:00:00+00:00",
        oos_end="2024-01-20T00:00:00+00:00",
        benchmark="none",
    )

    exit_code = cli._handle_run_ema(args)

    assert exit_code == 0
    request = recorded["request"]
    assert request.validation_split is not None
    assert request.validation_split.validation_split_id == "split-001"
    assert request.validation_split.target_type is ValidationTargetType.DATASET_SNAPSHOT
    assert request.validation_split.target_id == "snapshot-001"
    assert request.validation_split.warmup_bars == 5
    assert captured_payload["runner"] is not None


def test_build_ui_launch_command_includes_streamlit_args() -> None:
    command = cli._build_ui_launch_command(
        python_executable="/tmp/python",
        app_path=Path("/tmp/streamlit_app.py"),
        repository_root="/repo",
        data_dir="/repo/data",
        host="0.0.0.0",
        port=8502,
    )

    assert command == [
        "/tmp/python",
        "-m",
        "streamlit",
        "run",
        "/tmp/streamlit_app.py",
        "--server.headless",
        "true",
        "--server.address",
        "0.0.0.0",
        "--server.port",
        "8502",
        "--",
        "--repository-root",
        "/repo",
        "--data-dir",
        "/repo/data",
    ]


def test_handle_ui_streamlit_returns_130_on_keyboard_interrupt(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_streamlit_app_path",
        lambda: Path("/tmp/streamlit_app.py"),
    )

    def interrupting_run(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.subprocess, "run", interrupting_run)

    exit_code = cli._handle_ui_streamlit(
        argparse.Namespace(
            repository_root=".",
            data_dir=None,
            host="127.0.0.1",
            port=8501,
        )
    )

    assert exit_code == 130


def test_handle_ui_forwards_arguments(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_serve_ui(**kwargs) -> int:
        recorded.update(kwargs)
        return 0

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.api.serve_ui",
        fake_serve_ui,
    )

    exit_code = cli._handle_ui(
        argparse.Namespace(
            repository_root="/repo",
            data_dir="/repo/data",
            host="0.0.0.0",
            port=8501,
            cors_origin="http://localhost:4173",
        )
    )

    assert exit_code == 0
    assert recorded == {
        "host": "0.0.0.0",
        "port": 8501,
        "repository_root": "/repo",
        "data_dir": "/repo/data",
        "cors_origin": "http://localhost:4173",
    }


def test_handle_api_forwards_arguments(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_serve_api(**kwargs) -> int:
        recorded.update(kwargs)
        return 0

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.api.serve_api",
        fake_serve_api,
    )

    exit_code = cli._handle_api(
        argparse.Namespace(
            repository_root="/repo",
            data_dir="/repo/data",
            host="0.0.0.0",
            port=9000,
            cors_origin="http://localhost:4173",
        )
    )

    assert exit_code == 0
    assert recorded == {
        "host": "0.0.0.0",
        "port": 9000,
        "repository_root": "/repo",
        "data_dir": "/repo/data",
        "cors_origin": "http://localhost:4173",
    }


def test_handle_run_ema_returns_task_failure_payload(monkeypatch, tmp_path, capsys) -> None:
    class _FailureCode:
        value = "CONFIG_INVALID"

    class _Task:
        task_id = "single-run:run-002"
        status = type("_Status", (), {"value": "failed"})()
        failure_code = _FailureCode()
        failure_stage = "run_backtest_task_executor"
        failure_message = "invalid config"

    class _TaskWorkflowResult:
        task = _Task()
        output = None

    def fake_run_backtest_task_workflow(**kwargs):
        return _TaskWorkflowResult()

    monkeypatch.setattr(
        "crypto_backtest_workbench.app.workflows.run_backtest_task_workflow",
        fake_run_backtest_task_workflow,
    )

    data_dir = tmp_path / "data"
    snapshot_dir = data_dir / "datasets" / "snapshot-001"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot.json").write_text(
        """
        {
          "dataset_snapshot_id": "snapshot-001",
          "source": "binance",
          "exchange": "binance",
          "market_type": "linear_usdt_perpetual",
          "symbol": "BTC/USDT:USDT",
          "timeframe": "1h",
          "time_range_start": "2024-01-01T00:00:00+00:00",
          "time_range_end": "2024-01-20T00:00:00+00:00",
          "row_count": 100,
          "schema_version": "v1",
          "feature_version": "pending",
          "storage_uri": "datasets/snapshot-001",
          "created_at": "2024-01-20T00:00:00+00:00",
          "data_source": "fixture",
          "price_type": "last"
        }
        """.strip(),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        snapshot_id="snapshot-001",
        run_id="run-002",
        repository_root=".",
        data_dir=str(data_dir),
        fast_period=4,
        slow_period=4,
        qty_policy_ref="fixed_1",
        qty=1.0,
        initial_cash=1000.0,
        leverage=1.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        min_notional=0.0,
        validation_split_id="validation:cli",
        warmup_bars=0,
        is_start=None,
        is_end=None,
        oos_start=None,
        oos_end=None,
        benchmark="none",
    )

    exit_code = cli._handle_run_ema(args)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"task_status": "failed"' in captured.out
    assert '"failure_code": "CONFIG_INVALID"' in captured.out
    assert '"failure_stage": "run_backtest_task_executor"' in captured.out


def test_build_execution_constraints_supports_percent_of_cash_defaults() -> None:
    constraints = cli._build_execution_constraints(
        argparse.Namespace(
            qty_policy_ref="percent_of_cash",
            qty=None,
            cash_allocation_pct=50.0,
            initial_cash=1000.0,
            leverage=2.0,
            fee_rate=0.0,
            slippage_bps=0.0,
            min_notional=0.0,
        )
    )

    assert constraints.qty_by_policy == {}
    assert constraints.cash_allocation_pct_by_policy == {"percent_of_cash": 50.0}


def _snapshot() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_snapshot_id="snapshot-001",
        source="binance",
        exchange="binance",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
        time_range_end=datetime(2024, 1, 31, tzinfo=UTC),
        row_count=100,
        schema_version="v1",
        feature_version="pending",
        storage_uri="datasets/snapshot-001",
        data_source="fixture",
        price_type=PriceType.LAST,
    )
