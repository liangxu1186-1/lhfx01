from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.domain.models import BenchmarkConfig, CanonicalCandle, MarketType
from crypto_backtest_workbench.engine.analytics import compute_buy_and_hold_benchmark


def test_compute_buy_and_hold_benchmark_returns_summary_and_equity_curve() -> None:
    candles = _build_candles(
        [
            (100.0, 100.0),
            (100.0, 110.0),
            (110.0, 90.0),
        ]
    )

    output = compute_buy_and_hold_benchmark(
        run_id="run-001",
        candles=candles,
        config=BenchmarkConfig(benchmark_type="buy_and_hold"),
        initial_equity=1_000.0,
    )

    assert output.result.benchmark_type == "buy_and_hold"
    assert output.result.return_pct == -0.1
    assert round(output.result.max_drawdown, 6) == round((1100.0 - 900.0) / 1100.0, 6)
    assert output.result.equity_uri == "memory://benchmarks/run-001/buy_and_hold/equity.json"
    assert output.result.daily_returns_uri == "memory://benchmarks/run-001/buy_and_hold/daily_returns.json"
    assert [point.equity for point in output.equity_points] == [1000.0, 1100.0, 900.0]
    assert output.daily_returns[0].date == "2024-01-01"
    assert output.daily_returns[0].return_pct == -0.1


def test_compute_buy_and_hold_benchmark_aggregates_daily_returns_by_day_close() -> None:
    candles = _build_candles(
        [
            (100.0, 110.0),
            (110.0, 120.0),
            (120.0, 90.0),
        ],
        step=timedelta(days=1),
    )

    output = compute_buy_and_hold_benchmark(
        run_id="run-002",
        candles=candles,
        config=BenchmarkConfig(benchmark_type="buy_and_hold"),
        initial_equity=1_000.0,
    )

    assert [point.date for point in output.daily_returns] == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
    ]
    assert [round(point.return_pct, 6) for point in output.daily_returns] == [
        0.1,
        round((1200.0 - 1100.0) / 1100.0, 6),
        -0.25,
    ]
    assert output.result.sharpe != 0.0


def _build_candles(
    prices: list[tuple[float, float]],
    *,
    step: timedelta = timedelta(hours=1),
) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, (open_price, close_price) in enumerate(prices):
        timestamp = start + (step * index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=open_price,
                high=max(open_price, close_price),
                low=min(open_price, close_price),
                close=close_price,
                volume=10.0,
            )
        )
    return candles
