"""Single-position execution simulator for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    FillEvent,
    OrderRequest,
    RejectReasonCode,
    Side,
    SignalAction,
    SignalIntent,
    StructuredWarning,
    TradeRecord,
    WarningType,
)
from crypto_backtest_workbench.engine.analytics.metrics import EquityPoint
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot


@dataclass(slots=True)
class ExecutionConstraints:
    initial_cash: float
    leverage: float = 1.0
    fee_rate: float = 0.0
    slippage_bps: float = 0.0
    min_notional: float = 0.0
    qty_by_policy: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult:
    orders: list[OrderRequest]
    fills: list[FillEvent]
    trades: list[TradeRecord]
    warnings: list[StructuredWarning]
    equity_curve: list[EquityPoint]
    account: AccountSnapshot


@dataclass(slots=True)
class _OpenPosition:
    trade: TradeRecord
    reserved_margin: float


def simulate_signals(
    *,
    candles: list[CanonicalCandle],
    signals: list[SignalIntent],
    constraints: ExecutionConstraints,
) -> ExecutionResult:
    if constraints.leverage <= 0:
        raise ValueError("leverage must be greater than 0")

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp)
    index_by_timestamp = {candle.timestamp: index for index, candle in enumerate(sorted_candles)}
    scheduled_signals: dict[int, list[SignalIntent]] = {}
    warnings: list[StructuredWarning] = []

    for signal in sorted(signals, key=lambda item: item.timestamp):
        signal_index = index_by_timestamp.get(signal.timestamp)
        if signal_index is None:
            warnings.append(
                _warning(
                    run_id=signal.run_id,
                    warning_code="SIGNAL_TIMESTAMP_NOT_FOUND",
                    message=f"Signal timestamp {signal.timestamp.isoformat()} not present in candle set.",
                    payload={"signal_id": signal.signal_id},
                )
            )
            continue
        execution_index = signal_index + 1
        if execution_index >= len(sorted_candles):
            warnings.append(
                _warning(
                    run_id=signal.run_id,
                    warning_code="SIGNAL_SKIPPED_NO_NEXT_OPEN",
                    message="Signal skipped because no next bar open exists.",
                    payload={"signal_id": signal.signal_id},
                )
            )
            continue
        scheduled_signals.setdefault(execution_index, []).append(signal)

    orders: list[OrderRequest] = []
    fills: list[FillEvent] = []
    trades: list[TradeRecord] = []
    equity_curve: list[EquityPoint] = []

    account = AccountSnapshot(
        available_cash=constraints.initial_cash,
        used_margin=0.0,
        maintenance_margin=0.0,
        equity=constraints.initial_cash,
        unrealized_pnl=0.0,
    )
    position: _OpenPosition | None = None

    for index, candle in enumerate(sorted_candles):
        for signal in scheduled_signals.get(index, ()):
            signal_orders, signal_fills, signal_trades, signal_warnings, position = _execute_signal(
                signal=signal,
                candle=candle,
                constraints=constraints,
                account=account,
                position=position,
            )
            orders.extend(signal_orders)
            fills.extend(signal_fills)
            trades.extend(signal_trades)
            warnings.extend(signal_warnings)

        unrealized_pnl = _unrealized_pnl(position, candle.close)
        account.unrealized_pnl = unrealized_pnl
        account.equity = account.available_cash + account.used_margin + unrealized_pnl
        equity_curve.append(
            EquityPoint(
                timestamp=candle.timestamp,
                cash=account.available_cash,
                used_margin=account.used_margin,
                equity=account.equity,
                unrealized_pnl=unrealized_pnl,
            )
        )

    if position is not None:
        trades.append(position.trade)

    return ExecutionResult(
        orders=orders,
        fills=fills,
        trades=trades,
        warnings=warnings,
        equity_curve=equity_curve,
        account=account,
    )


def _execute_signal(
    *,
    signal: SignalIntent,
    candle: CanonicalCandle,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
    position: _OpenPosition | None,
) -> tuple[
    list[OrderRequest],
    list[FillEvent],
    list[TradeRecord],
    list[StructuredWarning],
    _OpenPosition | None,
]:
    if signal.action is SignalAction.HOLD:
        return [], [], [], [], position

    orders: list[OrderRequest] = []
    fills: list[FillEvent] = []
    trades: list[TradeRecord] = []
    warnings: list[StructuredWarning] = []

    if signal.action is SignalAction.OPEN:
        if position is not None:
            warnings.append(
                _warning(
                    run_id=signal.run_id,
                    warning_code="OPEN_IGNORED_POSITION_EXISTS",
                    message="Open signal ignored because a position is already open.",
                    payload={"signal_id": signal.signal_id, "trade_id": position.trade.trade_id},
                )
            )
            return orders, fills, trades, warnings, position
        order, fill, next_position = _open_position(signal, candle, constraints, account)
        orders.append(order)
        if fill is not None:
            fills.append(fill)
        return orders, fills, trades, warnings, next_position

    if signal.action is SignalAction.CLOSE:
        if position is None:
            warnings.append(
                _warning(
                    run_id=signal.run_id,
                    warning_code="CLOSE_IGNORED_NO_POSITION",
                    message="Close signal ignored because no position is open.",
                    payload={"signal_id": signal.signal_id},
                )
            )
            return orders, fills, trades, warnings, None
        order, fill = _close_position(signal, candle, constraints, account, position)
        orders.append(order)
        fills.append(fill)
        trades.append(position.trade)
        return orders, fills, trades, warnings, None

    if signal.action is SignalAction.REVERSE:
        if position is not None:
            close_order, close_fill = _close_position(signal, candle, constraints, account, position)
            orders.append(close_order)
            fills.append(close_fill)
            trades.append(position.trade)
            position = None
        open_order, open_fill, next_position = _open_position(signal, candle, constraints, account)
        orders.append(open_order)
        if open_fill is not None:
            fills.append(open_fill)
        return orders, fills, trades, warnings, next_position

    return orders, fills, trades, warnings, position


def _open_position(
    signal: SignalIntent,
    candle: CanonicalCandle,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
) -> tuple[OrderRequest, FillEvent | None, _OpenPosition | None]:
    qty = constraints.qty_by_policy.get(signal.qty_policy_ref, 0.0)
    order = OrderRequest(
        order_id=_next_id("order"),
        run_id=signal.run_id,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        side=signal.side,
        order_type="market",
        qty=qty,
        request_time=candle.timestamp,
        request_price=candle.open,
        status="pending",
    )
    reject_reason = _validate_open_order(qty=qty, price=candle.open, constraints=constraints, account=account)
    if reject_reason is not None:
        order.status = "rejected"
        order.reject_reason_code = reject_reason
        order.reject_payload = {"qty_policy_ref": signal.qty_policy_ref}
        return order, None, None

    fill_price = _apply_slippage(candle.open, signal.side, is_entry=True, slippage_bps=constraints.slippage_bps)
    fee = fill_price * qty * constraints.fee_rate
    margin = fill_price * qty / constraints.leverage
    account.available_cash -= margin + fee
    account.used_margin += margin
    account.equity = account.available_cash + account.used_margin
    order.status = "filled"

    trade = TradeRecord(
        trade_id=_next_id("trade"),
        run_id=signal.run_id,
        symbol=signal.symbol,
        side=signal.side,
        entry_time=candle.timestamp,
        entry_price=fill_price,
        exit_time=None,
        exit_price=None,
        qty=qty,
        fee=fee,
        entry_reason=signal.reason_code,
    )
    fill = FillEvent(
        fill_id=_next_id("fill"),
        run_id=signal.run_id,
        order_id=order.order_id,
        trade_id=trade.trade_id,
        fill_time=candle.timestamp,
        fill_price=fill_price,
        qty=qty,
        fee=fee,
        slippage_cost=abs(fill_price - candle.open) * qty,
    )
    return order, fill, _OpenPosition(trade=trade, reserved_margin=margin)


def _close_position(
    signal: SignalIntent,
    candle: CanonicalCandle,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
    position: _OpenPosition,
) -> tuple[OrderRequest, FillEvent]:
    trade = position.trade
    fill_price = _apply_slippage(candle.open, trade.side, is_entry=False, slippage_bps=constraints.slippage_bps)
    fee = fill_price * trade.qty * constraints.fee_rate
    gross_pnl = _realized_pnl(trade.side, trade.entry_price, fill_price, trade.qty)
    net_pnl = gross_pnl - trade.fee - fee

    account.used_margin -= position.reserved_margin
    account.available_cash += position.reserved_margin + gross_pnl - fee
    account.equity = account.available_cash + account.used_margin
    account.unrealized_pnl = 0.0

    trade.exit_time = candle.timestamp
    trade.exit_price = fill_price
    trade.gross_pnl = gross_pnl
    trade.fee += fee
    trade.net_pnl = net_pnl
    trade.return_pct = gross_pnl / (trade.entry_price * trade.qty) if trade.entry_price > 0 and trade.qty > 0 else 0.0
    trade.exit_reason = signal.reason_code

    order = OrderRequest(
        order_id=_next_id("order"),
        run_id=signal.run_id,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        side=trade.side,
        order_type="market",
        qty=trade.qty,
        request_time=candle.timestamp,
        request_price=candle.open,
        status="filled",
    )
    fill = FillEvent(
        fill_id=_next_id("fill"),
        run_id=signal.run_id,
        order_id=order.order_id,
        trade_id=trade.trade_id,
        fill_time=candle.timestamp,
        fill_price=fill_price,
        qty=trade.qty,
        fee=fee,
        slippage_cost=abs(fill_price - candle.open) * trade.qty,
    )
    return order, fill


def _validate_open_order(
    *,
    qty: float,
    price: float,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
) -> RejectReasonCode | None:
    if qty <= 0:
        return RejectReasonCode.INVALID_QTY
    notional = qty * price
    if constraints.min_notional > 0 and notional < constraints.min_notional:
        return RejectReasonCode.MIN_NOTIONAL
    required_margin = notional / constraints.leverage
    estimated_fee = notional * constraints.fee_rate
    if not account.has_margin_for(required_margin + estimated_fee):
        return RejectReasonCode.INSUFFICIENT_MARGIN
    return None


def _apply_slippage(price: float, side: Side, *, is_entry: bool, slippage_bps: float) -> float:
    if slippage_bps == 0:
        return price

    multiplier = slippage_bps / 10_000
    if _is_buy(side, is_entry):
        return price * (1 + multiplier)
    return price * (1 - multiplier)


def _is_buy(side: Side, is_entry: bool) -> bool:
    if side is Side.LONG:
        return is_entry
    if side is Side.SHORT:
        return not is_entry
    return True


def _realized_pnl(side: Side, entry_price: float, exit_price: float, qty: float) -> float:
    if side is Side.LONG:
        return (exit_price - entry_price) * qty
    if side is Side.SHORT:
        return (entry_price - exit_price) * qty
    return 0.0


def _unrealized_pnl(position: _OpenPosition | None, mark_price: float) -> float:
    if position is None:
        return 0.0
    return _realized_pnl(position.trade.side, position.trade.entry_price, mark_price, position.trade.qty)


def _warning(*, run_id: str, warning_code: str, message: str, payload: dict[str, object]) -> StructuredWarning:
    return StructuredWarning(
        warning_id=_next_id("warning"),
        run_id=run_id,
        warning_type=WarningType.EXECUTION_WARNING,
        warning_code=warning_code,
        severity="warning",
        message=message,
        payload_json=payload,
    )


def _next_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
