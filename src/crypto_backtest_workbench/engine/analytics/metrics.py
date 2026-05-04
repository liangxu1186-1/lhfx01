"""Minimal analytics helpers for Phase 1 single-run results."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Protocol

from crypto_backtest_workbench.domain.models import TradeRecord


@dataclass(slots=True)
class EquityPoint:
    timestamp: datetime
    cash: float
    used_margin: float
    equity: float
    unrealized_pnl: float


@dataclass(slots=True)
class RunMetrics:
    initial_equity: float
    final_equity: float
    total_return: float
    trade_count: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float = 0.0

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


class _EquityLike(Protocol):
    equity: float


def compute_max_drawdown(equity_curve: list[_EquityLike] | tuple[_EquityLike, ...]) -> float:
    peak_equity = 0.0
    max_drawdown = 0.0
    for point in equity_curve:
        equity = float(point.equity)
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
    return max_drawdown


def compute_run_metrics(
    *,
    initial_equity: float,
    final_equity: float,
    trades: list[TradeRecord],
    equity_curve: list[_EquityLike] | tuple[_EquityLike, ...] | None = None,
) -> RunMetrics:
    closed_trades = [trade for trade in trades if trade.exit_time is not None]
    trade_count = len(closed_trades)
    total_return = 0.0
    if initial_equity > 0:
        total_return = (final_equity - initial_equity) / initial_equity
    max_drawdown = compute_max_drawdown(equity_curve or [])

    if trade_count == 0:
        return RunMetrics(
            initial_equity=initial_equity,
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_drawdown,
            trade_count=0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
        )

    net_pnls = [trade.net_pnl for trade in closed_trades]
    winners = [pnl for pnl in net_pnls if pnl > 0]
    losers = [pnl for pnl in net_pnls if pnl < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = 0.0
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")

    return RunMetrics(
        initial_equity=initial_equity,
        final_equity=final_equity,
        total_return=total_return,
        max_drawdown=max_drawdown,
        trade_count=trade_count,
        win_rate=len(winners) / trade_count,
        profit_factor=profit_factor,
        expectancy=sum(net_pnls) / trade_count,
    )
