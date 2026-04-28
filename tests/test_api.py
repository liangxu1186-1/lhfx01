from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
import time
from urllib import error
from urllib import request

from crypto_backtest_workbench.app import api
from crypto_backtest_workbench.domain.models import CanonicalCandle, DatasetSnapshot, MarketType, PriceType
from crypto_backtest_workbench.storage.repositories import FileDatasetRepository


def test_workspace_api_returns_workspace_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-001")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        response = _request_json(server, "/api/workspace")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["source"]["dataset_count"] == 1
    assert response["source"]["run_count"] == 0
    assert response["datasets"][0]["dataset_snapshot_id"] == "snapshot-api-001"


def test_workspace_api_run_ema_executes_and_persists_run(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-002")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        run_response = _request_json(
            server,
            "/api/run-ema",
            payload={
                "snapshot_id": "snapshot-api-002",
                "run_id": "run-api-001",
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
        )
        workspace_response = _request_json(server, "/api/workspace")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert run_response["task_status"] == "success"
    assert run_response["run_id"] == "run-api-001"
    assert workspace_response["source"]["run_count"] == 1
    assert workspace_response["overview"]["summaries"][0]["run_id"] == "run-api-001"


def test_workspace_api_run_ema_supports_percent_of_cash_sizing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-cash-001")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        run_response = _request_json(
            server,
            "/api/run-ema",
            payload={
                "snapshot_id": "snapshot-api-cash-001",
                "run_id": "run-api-cash-001",
                "fast_period": 2,
                "slow_period": 3,
                "cash_allocation_pct": 50.0,
                "initial_cash": 10000.0,
                "leverage": 2.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
        )
        run_detail = _request_json(server, "/api/runs/run-api-cash-001")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert run_response["task_status"] == "success"
    constraints = run_detail["run"]["manifest"]["resolved_config_json"]["execution_constraints"]
    assert constraints["cash_allocation_pct_by_policy"] == {"percent_of_cash": 50.0}
    assert constraints["qty_by_policy"] == {}


def test_workspace_api_split_read_endpoints_return_expected_sections(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-003")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        _request_json(
            server,
            "/api/run-ema",
            payload={
                "snapshot_id": "snapshot-api-003",
                "run_id": "run-api-003",
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
        )
        datasets_response = _request_json(server, "/api/datasets")
        overview_response = _request_json(server, "/api/overview")
        overview_equity_response = _request_json(server, "/api/overview-equity?run_id=run-api-003")
        runs_response = _request_json(server, "/api/runs")
        tasks_response = _request_json(server, "/api/tasks")
        run_detail_response = _request_json(server, "/api/runs/run-api-003")
        task_detail_response = _request_json(server, "/api/tasks/single-run:run-api-003")
        parameters_response = _request_json(server, "/api/parameters")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert datasets_response["datasets"][0]["dataset_snapshot_id"] == "snapshot-api-003"
    assert overview_response["overview"]["summaries"][0]["run_id"] == "run-api-003"
    assert overview_response["overview"]["multi_run_equity"] == []
    assert overview_equity_response["multi_run_equity"]
    assert "run-api-003_equity" in overview_equity_response["multi_run_equity"][0]
    assert runs_response["runs"][0]["run_id"] == "run-api-003"
    assert tasks_response["tasks"][0]["task_id"] == "single-run:run-api-003"
    assert run_detail_response["run"]["run_id"] == "run-api-003"
    assert task_detail_response["task"]["task_id"] == "single-run:run-api-003"
    assert parameters_response["parameter_lab"]["rows"][0]["run_id"] == "run-api-003"


def test_workspace_api_research_notes_can_be_created_and_read_from_run_detail(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-note-001")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        _request_json(
            server,
            "/api/run-ema",
            payload={
                "snapshot_id": "snapshot-api-note-001",
                "run_id": "run-api-note-001",
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
        )
        create_response = _request_json(
            server,
            "/api/research-notes",
            payload={
                "target_type": "run",
                "target_id": "run-api-note-001",
                "author": "tester",
                "labels": ["candidate", "review"],
                "content": "样本外仍为正，先保留候选。",
            },
            method="POST",
        )
        notes_response = _request_json(
            server,
            "/api/research-notes?target_type=run&target_id=run-api-note-001",
        )
        run_detail_response = _request_json(server, "/api/runs/run-api-note-001")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert create_response["note"]["target_id"] == "run-api-note-001"
    assert create_response["note"]["labels"] == ["candidate", "review"]
    assert notes_response["research_notes"][0]["author"] == "tester"
    assert run_detail_response["run"]["research_notes"][0]["content"] == "样本外仍为正，先保留候选。"


def test_workspace_api_parameter_experiment_executes_in_background_and_is_queryable(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-parameter-001")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        submit_response = _request_json(
            server,
            "/api/parameter-experiments",
            payload={
                "experiment_id": "experiment-api-001",
                "snapshot_id": "snapshot-api-parameter-001",
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4, 5],
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        task_id = str(submit_response["task_id"])
        task_response = _wait_for_task_status(server, task_id, expected_status="success")
        experiments_response = _request_json(server, "/api/parameter-experiments")
        experiment_detail_response = _request_json(server, "/api/parameter-experiments/experiment-api-001")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert submit_response["experiment_id"] == "experiment-api-001"
    assert submit_response["planned_run_count"] == 4
    assert task_response["task"]["status"] == "success"
    assert experiments_response["parameter_experiments"][0]["experiment_id"] == "experiment-api-001"
    assert experiment_detail_response["parameter_experiment"]["experiment"]["experiment_id"] == "experiment-api-001"
    assert len(experiment_detail_response["parameter_experiment"]["execution"]["run_ids"]) == 4


def test_workspace_api_parameter_experiment_rejects_duplicate_experiment_id(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-parameter-002")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        _request_json(
            server,
            "/api/parameter-experiments",
            payload={
                "experiment_id": "experiment-api-duplicate",
                "snapshot_id": "snapshot-api-parameter-002",
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4, 5],
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        error_response = _request_error_json(
            server,
            "/api/parameter-experiments",
            payload={
                "experiment_id": "experiment-api-duplicate",
                "snapshot_id": "snapshot-api-parameter-002",
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4, 5],
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert error_response["status"] == 409
    assert "already exists" in error_response["body"]["error"]["message"]


def test_workspace_api_parameter_experiment_rejects_invalid_parameter_combinations(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-parameter-003")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        error_response = _request_error_json(
            server,
            "/api/parameter-experiments",
            payload={
                "experiment_id": "experiment-api-invalid",
                "snapshot_id": "snapshot-api-parameter-003",
                "search_type": "grid",
                "fast_periods": [5, 8],
                "slow_periods": [5, 13],
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert error_response["status"] == 400
    assert "fast_period < slow_period" in error_response["body"]["error"]["message"]


def test_workspace_api_parameter_experiment_batch_executes_and_returns_recommendations(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-batch-001", timeframe="1h")
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-batch-002", timeframe="4h")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        submit_response = _request_json(
            server,
            "/api/parameter-experiment-batches",
            payload={
                "batch_id": "batch-api-001",
                "snapshot_ids": ["snapshot-api-batch-001", "snapshot-api-batch-002"],
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4],
                "cash_allocation_pct": 100,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        task_id = str(submit_response["task_id"])
        task_response = _wait_for_task_status(server, task_id, expected_status="success")
        batches_response = _request_json(server, "/api/parameter-experiment-batches")
        batch_detail_response = _request_json(server, "/api/parameter-experiment-batches/batch-api-001")
        group = batch_detail_response["parameter_experiment_batch"]["parameter_groups"][0]
        group_target_id = f"batch-api-001:f{group['fast_period']}:s{group['slow_period']}:l{group['leverage']}"
        batch_note_response = _request_json(
            server,
            "/api/research-notes",
            payload={
                "target_type": "parameter_experiment_batch",
                "target_id": "batch-api-001",
                "author": "tester",
                "labels": ["candidate"],
                "content": "批次整体进入候选观察。",
            },
            method="POST",
        )
        group_note_response = _request_json(
            server,
            "/api/research-notes",
            payload={
                "target_type": "parameter_group",
                "target_id": group_target_id,
                "author": "tester",
                "labels": ["baseline"],
                "content": "参数组作为基准组。",
            },
            method="POST",
        )
        group_notes_response = _request_json(
            server,
            f"/api/research-notes?target_type=parameter_group&target_id={group_target_id}",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert submit_response["batch_id"] == "batch-api-001"
    assert submit_response["planned_experiment_count"] == 2
    assert submit_response["planned_run_count"] == 4
    assert task_response["task"]["status"] == "success"
    assert batches_response["parameter_experiment_batches"][0]["batch_id"] == "batch-api-001"
    assert batch_detail_response["parameter_experiment_batch"]["batch"]["batch_id"] == "batch-api-001"
    assert len(batch_detail_response["parameter_experiment_batch"]["experiments"]) == 2
    assert len(batch_detail_response["parameter_experiment_batch"]["run_rows"]) == 4
    assert "robust_candidates" in batch_detail_response["parameter_experiment_batch"]["recommendations"]
    assert "robust_candidate" in batch_detail_response["parameter_experiment_batch"]["scoring_rules"]
    assert "相邻参数稳定度 >= 50%，且至少有 1 个稳定邻居" in batch_detail_response["parameter_experiment_batch"]["scoring_rules"]["robust_candidate"]["thresholds"]
    assert "neighbor_stability_score" in batch_detail_response["parameter_experiment_batch"]["parameter_groups"][0]
    assert "score" in batch_detail_response["parameter_experiment_batch"]["parameter_groups"][0]
    assert "confidence" in batch_detail_response["parameter_experiment_batch"]["parameter_groups"][0]
    assert batch_note_response["note"]["target_type"] == "parameter_experiment_batch"
    assert group_note_response["note"]["target_id"] == group_target_id
    assert group_notes_response["research_notes"][0]["content"] == "参数组作为基准组。"


def test_workspace_api_delete_parameter_experiment_removes_runs_and_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-delete-experiment-001")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        submit_response = _request_json(
            server,
            "/api/parameter-experiments",
            payload={
                "experiment_id": "experiment-api-delete-001",
                "snapshot_id": "snapshot-api-delete-experiment-001",
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4],
                "cash_allocation_pct": 100,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        _wait_for_task_status(server, str(submit_response["task_id"]), expected_status="success")
        delete_response = _request_json(server, "/api/parameter-experiments/experiment-api-delete-001", method="DELETE")
        experiments_response = _request_json(server, "/api/parameter-experiments")
        runs_response = _request_json(server, "/api/runs")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert delete_response["deleted"] is True
    assert delete_response["experiment_id"] == "experiment-api-delete-001"
    assert experiments_response["parameter_experiments"] == []
    assert runs_response["runs"] == []


def test_workspace_api_delete_parameter_experiment_batch_removes_child_experiments_and_runs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-delete-batch-001", timeframe="1h")
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-delete-batch-002", timeframe="4h")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        submit_response = _request_json(
            server,
            "/api/parameter-experiment-batches",
            payload={
                "batch_id": "batch-api-delete-001",
                "snapshot_ids": ["snapshot-api-delete-batch-001", "snapshot-api-delete-batch-002"],
                "search_type": "grid",
                "fast_periods": [2],
                "slow_periods": [4],
                "cash_allocation_pct": 100,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        _wait_for_task_status(server, str(submit_response["task_id"]), expected_status="success")
        delete_response = _request_json(server, "/api/parameter-experiment-batches/batch-api-delete-001", method="DELETE")
        batches_response = _request_json(server, "/api/parameter-experiment-batches")
        experiments_response = _request_json(server, "/api/parameter-experiments")
        runs_response = _request_json(server, "/api/runs")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert delete_response["deleted"] is True
    assert delete_response["batch_id"] == "batch-api-delete-001"
    assert batches_response["parameter_experiment_batches"] == []
    assert experiments_response["parameter_experiments"] == []
    assert runs_response["runs"] == []


def test_workspace_api_delete_run_removes_persisted_run(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-004")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        _request_json(
            server,
            "/api/run-ema",
            payload={
                "snapshot_id": "snapshot-api-004",
                "run_id": "run-api-004",
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "fixed_1",
                "qty": 0.01,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
        )
        delete_response = _request_json(server, "/api/runs/run-api-004", method="DELETE")
        runs_response = _request_json(server, "/api/runs")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert delete_response["deleted"] is True
    assert delete_response["run_id"] == "run-api-004"
    assert runs_response["runs"] == []


def test_workspace_api_delete_run_prunes_parameter_experiment_and_batch_indexes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-delete-run-batch-001", timeframe="1h")
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-delete-run-batch-002", timeframe="4h")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        submit_response = _request_json(
            server,
            "/api/parameter-experiment-batches",
            payload={
                "batch_id": "batch-api-delete-run-index-001",
                "snapshot_ids": ["snapshot-api-delete-run-batch-001", "snapshot-api-delete-run-batch-002"],
                "search_type": "grid",
                "fast_periods": [2, 3],
                "slow_periods": [4],
                "cash_allocation_pct": 100,
                "initial_cash": 10000.0,
                "leverage": 1.0,
                "fee_rate": 0.0,
                "slippage_bps": 0.0,
                "min_notional": 0.0,
                "benchmark": "buy_and_hold",
            },
            method="POST",
        )
        _wait_for_task_status(server, str(submit_response["task_id"]), expected_status="success")
        batch_detail_before = _request_json(server, "/api/parameter-experiment-batches/batch-api-delete-run-index-001")
        experiment_id = str(batch_detail_before["parameter_experiment_batch"]["experiments"][0]["experiment"]["experiment_id"])
        experiment_detail_before = _request_json(server, f"/api/parameter-experiments/{experiment_id}")
        run_id = str(experiment_detail_before["parameter_experiment"]["execution"]["run_ids"][0])

        delete_response = _request_json(server, f"/api/runs/{run_id}", method="DELETE")
        batch_detail_after = _request_json(server, "/api/parameter-experiment-batches/batch-api-delete-run-index-001")
        experiment_detail_after = _request_json(server, f"/api/parameter-experiments/{experiment_id}")
        experiments_response = _request_json(server, "/api/parameter-experiments")
        batches_response = _request_json(server, "/api/parameter-experiment-batches")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert delete_response["deleted"] is True
    assert experiment_id in delete_response["experiment_ids"]
    assert "batch-api-delete-run-index-001" in delete_response["batch_ids"]
    assert len(experiment_detail_before["parameter_experiment"]["execution"]["run_ids"]) == 2
    assert len(experiment_detail_after["parameter_experiment"]["execution"]["run_ids"]) == 1
    assert len(batch_detail_before["parameter_experiment_batch"]["execution"]["run_ids"]) == 4
    assert len(batch_detail_after["parameter_experiment_batch"]["execution"]["run_ids"]) == 3
    experiment_summary = next(
        item for item in experiments_response["parameter_experiments"] if item["experiment_id"] == experiment_id
    )
    batch_summary = next(
        item for item in batches_response["parameter_experiment_batches"] if item["batch_id"] == "batch-api-delete-run-index-001"
    )
    assert experiment_summary["run_count"] == 1
    assert batch_summary["run_count"] == 3


def test_workspace_api_delete_dataset_removes_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-api-005")
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        delete_response = _request_json(server, "/api/datasets/snapshot-api-005", method="DELETE")
        datasets_response = _request_json(server, "/api/datasets")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert delete_response["deleted"] is True
    assert delete_response["dataset_snapshot_id"] == "snapshot-api-005"
    assert datasets_response["datasets"] == []


def test_workspace_api_ingest_endpoint_delegates_to_workflow(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}

    def fake_ingest_dataset_workflow(**kwargs):
        recorded.update(kwargs)

        class _Snapshot:
            dataset_snapshot_id = "snapshot-ingest-001"
            row_count = 5

        class _Result:
            snapshot = _Snapshot()
            snapshot_path = Path("/tmp/snapshot.json")
            candles_path = Path("/tmp/candles.csv")
            integrity_report_path = Path("/tmp/integrity.json")
            dropped_open_candle = True

        return _Result()

    monkeypatch.setattr(api, "ingest_dataset_workflow", fake_ingest_dataset_workflow)

    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=tmp_path / "data",
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        response = _request_json(
            server,
            "/api/ingest",
            payload={
                "exchange": "binanceusdm",
                "symbol": "BTC/USDT:USDT",
                "timeframe": "1h",
                "since": "2024-01-01T00:00:00+00:00",
                "until": "2024-01-02T00:00:00+00:00",
                "market_type": "linear_usdt_perpetual",
                "price_type": "last",
                "limit": 1000,
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["dataset_snapshot_id"] == "snapshot-ingest-001"
    assert recorded["exchange"] == "binanceusdm"
    assert recorded["repository_root"] == tmp_path.resolve()


def test_ui_server_serves_react_index_and_api(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_snapshot(data_dir=data_dir, snapshot_id="snapshot-ui-001")
    frontend_dist_dir = tmp_path / "frontend-dist"
    frontend_dist_dir.mkdir()
    (frontend_dist_dir / "index.html").write_text("<html><body>react-ui</body></html>", encoding="utf-8")

    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
        frontend_dist_dir=frontend_dist_dir,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        ui_response = _request_text(server, "/")
        workspace_response = _request_json(server, "/api/workspace")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert "react-ui" in ui_response
    assert workspace_response["datasets"][0]["dataset_snapshot_id"] == "snapshot-ui-001"


def test_print_startup_banner_emits_success_marker(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    server = api.create_api_server(
        host="127.0.0.1",
        port=0,
        repository_root=tmp_path,
        data_dir=data_dir,
    )
    try:
        api._print_startup_banner(server=server, mode="api")
    finally:
        server.server_close()

    captured = capsys.readouterr()
    assert "=== CBW STARTED ===" in captured.out
    assert "status: 启动成功" in captured.out
    assert "health:" in captured.out


def _request_json(
    server: api.WorkspaceApiServer,
    path: str,
    payload: dict[str, object] | None = None,
    method: str | None = None,
):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    resolved_method = method or ("POST" if payload is not None else "GET")
    if payload is None and resolved_method == "GET":
        with request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    http_request = request.Request(
        url,
        data=body,
        headers=headers,
        method=resolved_method,
    )
    with request.urlopen(http_request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(server: api.WorkspaceApiServer, path: str) -> str:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    with request.urlopen(url, timeout=2) as response:
        return response.read().decode("utf-8")


def _request_error_json(
    server: api.WorkspaceApiServer,
    path: str,
    payload: dict[str, object] | None = None,
    method: str | None = None,
):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    resolved_method = method or ("POST" if payload is not None else "GET")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    http_request = request.Request(
        url,
        data=body,
        headers=headers,
        method=resolved_method,
    )
    try:
        with request.urlopen(http_request, timeout=2) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except error.HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8"))}


def _wait_for_task_status(
    server: api.WorkspaceApiServer,
    task_id: str,
    *,
    expected_status: str,
    timeout_seconds: float = 3.0,
):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = _request_json(server, f"/api/tasks/{task_id}")
        if response["task"]["status"] == expected_status:
            return response
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for task {task_id} to reach {expected_status}")


def _seed_snapshot(*, data_dir: Path, snapshot_id: str, timeframe: str = "1h") -> None:
    dataset_repository = FileDatasetRepository(data_dir)
    candles = _build_candles(timeframe=timeframe)
    snapshot = DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source="binanceusdm",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe=timeframe,
        time_range_start=candles[0].timestamp,
        time_range_end=candles[-1].timestamp,
        row_count=len(candles),
        schema_version="v1",
        feature_version="pending",
        storage_uri=f"datasets/{snapshot_id}",
        data_source="fixture",
        price_type=PriceType.LAST,
    )
    dataset_repository.save_snapshot(snapshot)
    dataset_repository.save_candles(snapshot_id, candles)


def _build_candles(*, timeframe: str = "1h") -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    close_prices = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]
    candles: list[CanonicalCandle] = []
    for index, close in enumerate(close_prices):
        timestamp = start + timedelta(hours=index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binanceusdm",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe=timeframe,
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=10.0 + index,
                price_type=PriceType.LAST,
                data_source="fixture",
            )
        )
    return candles
