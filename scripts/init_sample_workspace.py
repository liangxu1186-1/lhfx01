from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from crypto_backtest_workbench.app.readmodels.workspace import write_workspace_snapshot  # noqa: E402
from crypto_backtest_workbench.app.workflows.run_backtest import (  # noqa: E402
    RunBacktestWorkflowRequest,
    run_backtest_workflow,
)
from crypto_backtest_workbench.domain.models import (  # noqa: E402
    CanonicalCandle,
    DatasetSnapshot,
    MarketType,
    PriceType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints  # noqa: E402
from crypto_backtest_workbench.storage.repositories import (  # noqa: E402
    FileDatasetRepository,
    FileFeatureRepository,
    FileRunRepository,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed a minimal offline workspace for a fresh local clone.")
    parser.add_argument("--repository-root", default=str(REPOSITORY_ROOT))
    parser.add_argument("--data-dir")
    parser.add_argument("--force", action="store_true", help="Replace existing sample datasets, features, and runs.")
    parser.add_argument(
        "--export-demo",
        action="store_true",
        help="Also refresh frontend/public/demo/workspace.json from the seeded sample workspace.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repository_root = Path(args.repository_root).resolve()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else repository_root / "data"

    prepare_data_dir(data_dir=data_dir, force=args.force)
    seed_sample_workspace(repository_root=repository_root, data_dir=data_dir, export_demo=args.export_demo)
    return 0


def prepare_data_dir(*, data_dir: Path, force: bool) -> None:
    managed_dirs = ("datasets", "features", "runs")
    occupied = [
        name
        for name in managed_dirs
        if (data_dir / name).exists() and any((data_dir / name).iterdir())
    ]
    if occupied and not force:
        joined = ", ".join(occupied)
        raise SystemExit(
            f"{data_dir} already contains {joined}. Re-run with --force to rebuild the sample workspace."
        )

    for name in managed_dirs:
        target = data_dir / name
        if force and target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)


def seed_sample_workspace(*, repository_root: Path, data_dir: Path, export_demo: bool) -> None:
    dataset_repository = FileDatasetRepository(data_dir)
    feature_repository = FileFeatureRepository(data_dir)
    run_repository = FileRunRepository(data_dir)

    hourly_snapshot = _save_snapshot(
        data_dir=data_dir,
        dataset_repository=dataset_repository,
        snapshot_id="sample-btc-1h",
        timeframe="1h",
        candles=_build_hourly_candles(),
    )
    intraday_snapshot = _save_snapshot(
        data_dir=data_dir,
        dataset_repository=dataset_repository,
        snapshot_id="sample-btc-5m",
        timeframe="5m",
        candles=_build_intraday_candles(timeframe="5m", bar_count=96),
    )

    workflow_result = run_backtest_workflow(
        dataset_repository=dataset_repository,
        feature_repository=feature_repository,
        request=RunBacktestWorkflowRequest(
            run_id="sample-ema-crossover-1h",
            snapshot=hourly_snapshot,
            strategy_params={
                "strategy_name": "ema_crossover",
                "fast_period": 2,
                "slow_period": 3,
                "qty_policy_ref": "sample_fixed_qty",
            },
            constraints=ExecutionConstraints(
                initial_cash=10_000.0,
                leverage=1.0,
                fee_rate=0.0004,
                qty_by_policy={"sample_fixed_qty": 1.0},
            ),
            enable_buy_and_hold_benchmark=True,
        ),
    )
    run_repository.save_single_run_result(workflow_result.single_run_result)

    print(f"Seeded sample workspace in {data_dir}")
    print(f"- dataset: {hourly_snapshot.dataset_snapshot_id}")
    print(f"- dataset: {intraday_snapshot.dataset_snapshot_id}")
    print(f"- run: sample-ema-crossover-1h")
    if export_demo:
        workspace_path = repository_root / "frontend" / "public" / "demo" / "workspace.json"
        write_workspace_snapshot(data_dir=data_dir, output_path=workspace_path)
        print(f"- demo snapshot: {workspace_path}")


def _save_snapshot(
    *,
    data_dir: Path,
    dataset_repository: FileDatasetRepository,
    snapshot_id: str,
    timeframe: str,
    candles: list[CanonicalCandle],
) -> DatasetSnapshot:
    snapshot = DatasetSnapshot(
        dataset_snapshot_id=snapshot_id,
        source="sample-fixture",
        exchange="binanceusdm",
        market_type=MarketType.LINEAR_USDT_PERPETUAL,
        symbol="BTC/USDT:USDT",
        timeframe=timeframe,
        time_range_start=candles[0].timestamp,
        time_range_end=candles[-1].timestamp,
        row_count=len(candles),
        schema_version="v1",
        feature_version="pending",
        storage_uri=str((data_dir / "datasets" / snapshot_id).resolve()),
        data_source="sample_fixture",
        price_type=PriceType.LAST,
    )
    dataset_repository.save_snapshot(snapshot)
    dataset_repository.save_candles(snapshot.dataset_snapshot_id, candles)
    return snapshot


def _build_hourly_candles() -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    close_prices = [100.0, 98.0, 101.0, 105.0, 102.0, 99.0, 97.0, 103.0, 108.0]
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
                open=close - 1.0,
                high=close + 1.5,
                low=close - 2.0,
                close=close,
                volume=100.0 + index,
                price_type=PriceType.LAST,
                data_source="sample_fixture",
            )
        )
    return candles


def _build_intraday_candles(*, timeframe: str, bar_count: int) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    step = timedelta(minutes=5) if timeframe == "5m" else timedelta(minutes=1)
    candles: list[CanonicalCandle] = []
    for index in range(bar_count):
        base = 100.0 + (index * 0.15)
        wave = ((index % 12) - 6) * 0.08
        close = base + wave
        timestamp = start + (step * index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binanceusdm",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe=timeframe,
                open=close - 0.05,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=20.0 + index,
                price_type=PriceType.LAST,
                data_source="sample_fixture",
            )
        )
    return candles


if __name__ == "__main__":
    raise SystemExit(main())
