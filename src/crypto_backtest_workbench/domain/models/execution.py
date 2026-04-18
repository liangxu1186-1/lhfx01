"""Execution-layer domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models.common import (
    PriceType,
    RejectReasonCode,
    Side,
    SignalAction,
    WarningType,
    now_utc,
)


@dataclass(slots=True)
class ExecutionPolicy:
    execution_policy_id: str
    signal_timing: str
    fill_timing: str
    price_field_used: str
    allow_same_bar_exit: bool
    version: str


@dataclass(slots=True)
class SignalIntent:
    signal_id: str
    run_id: str
    timestamp: datetime
    symbol: str
    action: SignalAction
    side: Side
    qty_policy_ref: str
    reason_code: str
    signal_score: float | None = None
    meta_json: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRequest:
    order_id: str
    run_id: str
    signal_id: str
    symbol: str
    side: Side
    order_type: str
    qty: float
    request_time: datetime
    request_price: float | None
    status: str
    reject_reason_code: RejectReasonCode | None = None
    reject_payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FillEvent:
    fill_id: str
    run_id: str
    order_id: str
    trade_id: str | None
    fill_time: datetime
    fill_price: float
    qty: float
    fee: float
    slippage_cost: float


@dataclass(slots=True)
class TradeRecord:
    trade_id: str
    run_id: str
    symbol: str
    side: Side
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None
    exit_price: float | None
    qty: float
    gross_pnl: float = 0.0
    fee: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    holding_bars: int = 0
    entry_reason: str = ""
    exit_reason: str = ""


@dataclass(slots=True)
class BenchmarkConfig:
    benchmark_type: str
    hold_bars: int | None = None
    price_type: PriceType = PriceType.LAST


@dataclass(slots=True)
class BenchmarkResult:
    benchmark_id: str
    run_id: str
    benchmark_type: str
    return_pct: float
    max_drawdown: float
    sharpe: float
    equity_uri: str
    daily_returns_uri: str | None = None


@dataclass(slots=True)
class StructuredWarning:
    warning_id: str
    run_id: str
    warning_type: WarningType
    warning_code: str
    severity: str
    message: str
    payload_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=now_utc)

