from __future__ import annotations

import json

import pytest

from crypto_backtest_workbench.app import streamlit_app


def test_load_dataset_snapshots_reads_persisted_snapshots(tmp_path) -> None:
    snapshot_dir = tmp_path / "datasets" / "snapshot-001"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "dataset_snapshot_id": "snapshot-001",
                "source": "binance",
                "exchange": "binance",
                "market_type": "linear_usdt_perpetual",
                "symbol": "BTC/USDT:USDT",
                "timeframe": "1h",
                "time_range_start": "2024-01-01T00:00:00+00:00",
                "time_range_end": "2024-01-02T00:00:00+00:00",
                "row_count": 24,
                "schema_version": "v1",
                "feature_version": "pending",
                "storage_uri": "datasets/snapshot-001",
                "data_source": "ccxt_rest",
                "price_type": "last",
                "created_at": "2024-01-02T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    snapshots = streamlit_app._load_dataset_snapshots(tmp_path)

    assert len(snapshots) == 1
    assert snapshots[0].dataset_snapshot_id == "snapshot-001"
    assert snapshots[0].symbol == "BTC/USDT:USDT"


def test_parse_json_input_requires_object() -> None:
    with pytest.raises(ValueError, match="必须是 JSON object"):
        streamlit_app._parse_json_input('["bad"]', field_name="测试 JSON")
