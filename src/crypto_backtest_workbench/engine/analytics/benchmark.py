"""Minimal buy-and-hold benchmark helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import sqrt

from crypto_backtest_workbench.domain.models import BenchmarkConfig, BenchmarkResult, CanonicalCandle


@dataclass(slots=True, frozen=True)
class BenchmarkEquityPoint:
    timestamp: datetime
    equity: float
    return_pct: float
    drawdown: float

    def as_dict(self) -> dict[str, float | datetime]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class BenchmarkDailyReturn:
    date: str
    return_pct: float

    def as_dict(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class BuyAndHoldBenchmarkOutput:
    result: BenchmarkResult
    equity_points: tuple[BenchmarkEquityPoint, ...]
    daily_returns: tuple[BenchmarkDailyReturn, ...]


def compute_buy_and_hold_benchmark(
    *,
    run_id: str,
    candles: list[CanonicalCandle],
    config: BenchmarkConfig,
    initial_equity: float,
    benchmark_id: str | None = None,
    equity_uri: str | None = None,
    daily_returns_uri: str | None = None,
) -> BuyAndHoldBenchmarkOutput:
    if config.benchmark_type != "buy_and_hold":
        raise ValueError("Only buy_and_hold is supported by this helper")
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    if not candles:
        raise ValueError("candles must not be empty")

    ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
    entry_price = ordered[0].open
    qty = initial_equity / entry_price
    equity_points = _build_equity_points(qty=qty, candles=ordered, initial_equity=initial_equity)
    daily_returns = _build_daily_returns(equity_points=equity_points, initial_equity=initial_equity)
    final_equity = equity_points[-1].equity
    return_pct = (final_equity - initial_equity) / initial_equity

    benchmark_result = BenchmarkResult(
        benchmark_id=benchmark_id or f"{run_id}:buy_and_hold",
        run_id=run_id,
        benchmark_type=config.benchmark_type,
        return_pct=return_pct,
        max_drawdown=max(point.drawdown for point in equity_points),
        sharpe=_compute_sharpe(daily_returns),
        equity_uri=equity_uri or f"memory://benchmarks/{run_id}/buy_and_hold/equity.json",
        daily_returns_uri=daily_returns_uri
        or f"memory://benchmarks/{run_id}/buy_and_hold/daily_returns.json",
    )
    return BuyAndHoldBenchmarkOutput(
        result=benchmark_result,
        equity_points=equity_points,
        daily_returns=daily_returns,
    )


def _build_equity_points(
    *,
    qty: float,
    candles: tuple[CanonicalCandle, ...],
    initial_equity: float,
) -> tuple[BenchmarkEquityPoint, ...]:
    peak_equity = initial_equity
    points: list[BenchmarkEquityPoint] = []
    for candle in candles:
        equity = qty * candle.close
        peak_equity = max(peak_equity, equity)
        drawdown = 0.0
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
        points.append(
            BenchmarkEquityPoint(
                timestamp=candle.timestamp,
                equity=equity,
                return_pct=(equity - initial_equity) / initial_equity,
                drawdown=drawdown,
            )
        )
    return tuple(points)


def _build_daily_returns(
    *,
    equity_points: tuple[BenchmarkEquityPoint, ...],
    initial_equity: float,
) -> tuple[BenchmarkDailyReturn, ...]:
    by_day: dict[str, float] = {}
    for point in equity_points:
        by_day[point.timestamp.date().isoformat()] = point.equity

    daily_returns: list[BenchmarkDailyReturn] = []
    previous_equity = initial_equity
    for date, equity in sorted(by_day.items()):
        daily_returns.append(
            BenchmarkDailyReturn(
                date=date,
                return_pct=(equity - previous_equity) / previous_equity,
            )
        )
        previous_equity = equity
    return tuple(daily_returns)


def _compute_sharpe(daily_returns: tuple[BenchmarkDailyReturn, ...]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    returns = [point.return_pct for point in daily_returns]
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
    if variance == 0:
        return 0.0
    return (mean_return / sqrt(variance)) * sqrt(365)
