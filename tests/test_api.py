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
    assert runs_response["runs"][0]["run_id"] == "run-api-003"
    assert tasks_response["tasks"][0]["task_id"] == "single-run:run-api-003"
    assert run_detail_response["run"]["run_id"] == "run-api-003"
    assert task_detail_response["task"]["task_id"] == "single-run:run-api-003"
    assert parameters_response["parameter_lab"]["rows"][0]["run_id"] == "run-api-003"


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


def _seed_snapshot(*, data_dir: Path, snapshot_id: str) -> None:
    dataset_repository = FileDatasetRepository(data_dir)
    candles = _build_candles()
    snapshot = DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source="binanceusdm",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe="1h",
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


def _build_candles() -> list[CanonicalCandle]:
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
                timeframe="1h",
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
