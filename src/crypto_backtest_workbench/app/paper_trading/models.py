"""Paper-trading domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_backtest_workbench.domain.models import (
    FillEvent,
    OrderRequest,
    StructuredWarning,
    TradeRecord,
    now_utc,
)
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot


PAPER_TRADING_MODEL_VERSION = "paper-trading-v1"


@dataclass(slots=True)
class PaperPosition:
    trade: TradeRecord
    reserved_margin: float
    entry_execution_index: int


@dataclass(slots=True)
class PaperCheckpoint:
    last_strategy_bar_time: datetime | None = None
    last_execution_bar_time: datetime | None = None
    last_signal_time: datetime | None = None
    execution_bar_count: int = 0


@dataclass(slots=True)
class PaperSession:
    session_id: str
    stable_candidate_id: str
    source_run_id: str
    strategy_name: str
    symbol: str
    exchange: str
    market_type: str
    price_type: str
    strategy_timeframe: str
    execution_timeframe: str
    strategy_params: dict[str, object]
    execution_constraints: dict[str, object]
    account: AccountSnapshot
    checkpoint: PaperCheckpoint = field(default_factory=PaperCheckpoint)
    position: PaperPosition | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    model_version: str = PAPER_TRADING_MODEL_VERSION


@dataclass(slots=True)
class PaperTickResult:
    session: PaperSession
    strategy_bar_count: int
    execution_bar_count: int
    new_signal_count: int
    order_count: int
    fill_count: int
    closed_trade_count: int
    warning_count: int
    orders: list[OrderRequest]
    fills: list[FillEvent]
    trades: list[TradeRecord]
    warnings: list[StructuredWarning]

