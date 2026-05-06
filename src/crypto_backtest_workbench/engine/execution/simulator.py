"""Single-position execution simulator for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
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


_MARGIN_CHECK_REL_TOLERANCE = 1e-9
_MARGIN_CHECK_ABS_TOLERANCE = 1e-9


@dataclass(slots=True)
class ExecutionConstraints:
    initial_cash: float
    leverage: float = 1.0
    fee_rate: float = 0.0
    slippage_bps: float = 0.0
    min_notional: float = 0.0
    qty_by_policy: dict[str, float] = field(default_factory=dict)
    cash_allocation_pct_by_policy: dict[str, float] = field(default_factory=dict)
    risk_pct_per_trade_by_policy: dict[str, float] = field(default_factory=dict)
    max_equity_drawdown_pct: float | None = None
    cooldown_after_consecutive_stop_losses: int | None = None
    cooldown_bars: int | None = None
    cooldown_only_short_holding_bars: int | None = None


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
    entry_index: int


def simulate_signals(
    *,
    candles: list[CanonicalCandle],
    signals: list[SignalIntent],
    constraints: ExecutionConstraints,
) -> ExecutionResult:
    if constraints.leverage <= 0:
        raise ValueError("leverage must be greater than 0")
    for allocation_pct in constraints.cash_allocation_pct_by_policy.values():
        if allocation_pct <= 0 or allocation_pct > 100:
            raise ValueError("cash_allocation_pct must be in (0, 100]")
    for risk_pct in constraints.risk_pct_per_trade_by_policy.values():
        if risk_pct <= 0 or risk_pct >= 1:
            raise ValueError("risk_pct_per_trade must be in (0, 1)")
    if constraints.max_equity_drawdown_pct is not None and not 0 < constraints.max_equity_drawdown_pct < 1:
        raise ValueError("max_equity_drawdown_pct must be in (0, 1)")
    if constraints.cooldown_after_consecutive_stop_losses is not None and constraints.cooldown_after_consecutive_stop_losses <= 0:
        raise ValueError("cooldown_after_consecutive_stop_losses must be positive")
    if constraints.cooldown_bars is not None and constraints.cooldown_bars <= 0:
        raise ValueError("cooldown_bars must be positive")
    if constraints.cooldown_only_short_holding_bars is not None and constraints.cooldown_only_short_holding_bars <= 0:
        raise ValueError("cooldown_only_short_holding_bars must be positive")

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
    peak_equity = constraints.initial_cash
    cooldown_until_index = -1
    consecutive_protected_stop_losses = 0

    for index, candle in enumerate(sorted_candles):
        if position is not None:
            sltp_order, sltp_fill, closed_position = _maybe_close_for_planned_sltp(
                candle=candle,
                candle_index=index,
                constraints=constraints,
                account=account,
                position=position,
            )
            if closed_position is not None:
                orders.append(sltp_order)
                fills.append(sltp_fill)
                trades.append(closed_position.trade)
                if _is_protected_stop_loss(closed_position.trade, constraints=constraints):
                    consecutive_protected_stop_losses += 1
                    if (
                        constraints.cooldown_after_consecutive_stop_losses is not None
                        and constraints.cooldown_bars is not None
                        and consecutive_protected_stop_losses >= constraints.cooldown_after_consecutive_stop_losses
                    ):
                        cooldown_until_index = max(cooldown_until_index, index + constraints.cooldown_bars)
                        consecutive_protected_stop_losses = 0
                else:
                    consecutive_protected_stop_losses = 0
                position = None
        peak_equity = max(peak_equity, account.equity)
        drawdown_guard_blocks_open = (
            constraints.max_equity_drawdown_pct is not None
            and peak_equity > 0
            and (peak_equity - account.equity) / peak_equity >= constraints.max_equity_drawdown_pct
        )
        cooldown_blocks_open = index < cooldown_until_index

        for signal in scheduled_signals.get(index, ()):
            if signal.action is SignalAction.OPEN and (drawdown_guard_blocks_open or cooldown_blocks_open):
                warnings.append(
                    _warning(
                        run_id=signal.run_id,
                        warning_code="OPEN_SKIPPED_DRAWDOWN_PROTECTION",
                        message="Open signal skipped by drawdown protection.",
                        payload={
                            "signal_id": signal.signal_id,
                            "drawdown_guard_blocks_open": drawdown_guard_blocks_open,
                            "cooldown_blocks_open": cooldown_blocks_open,
                            "cooldown_until_index": cooldown_until_index,
                        },
                    )
                )
                continue
            signal_orders, signal_fills, signal_trades, signal_warnings, position = _execute_signal(
                signal=signal,
                candle=candle,
                candle_index=index,
                constraints=constraints,
                account=account,
                position=position,
            )
            orders.extend(signal_orders)
            fills.extend(signal_fills)
            trades.extend(signal_trades)
            warnings.extend(signal_warnings)
            if position is not None and position.trade.entry_time == candle.timestamp:
                sltp_order, sltp_fill, closed_position = _maybe_close_for_planned_sltp(
                    candle=candle,
                    candle_index=index,
                    constraints=constraints,
                    account=account,
                    position=position,
                )
                if closed_position is not None:
                    orders.append(sltp_order)
                    fills.append(sltp_fill)
                    trades.append(closed_position.trade)
                    if _is_protected_stop_loss(closed_position.trade, constraints=constraints):
                        consecutive_protected_stop_losses += 1
                        if (
                            constraints.cooldown_after_consecutive_stop_losses is not None
                            and constraints.cooldown_bars is not None
                            and consecutive_protected_stop_losses >= constraints.cooldown_after_consecutive_stop_losses
                        ):
                            cooldown_until_index = max(cooldown_until_index, index + constraints.cooldown_bars)
                            consecutive_protected_stop_losses = 0
                    else:
                        consecutive_protected_stop_losses = 0
                    position = None

        unrealized_pnl = _unrealized_pnl(position, candle.close)
        account.unrealized_pnl = unrealized_pnl
        account.equity = account.available_cash + account.used_margin + unrealized_pnl
        peak_equity = max(peak_equity, account.equity)
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


def _is_protected_stop_loss(trade: TradeRecord, *, constraints: ExecutionConstraints) -> bool:
    if not str(trade.exit_reason or "").startswith("stop_loss"):
        return False
    holding_limit = constraints.cooldown_only_short_holding_bars
    if holding_limit is not None and trade.holding_bars > holding_limit:
        return False
    return True


def _execute_signal(
    *,
    signal: SignalIntent,
    candle: CanonicalCandle,
    candle_index: int,
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
        order, fill, next_position = _open_position(signal, candle, candle_index, constraints, account)
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
        order, fill = _close_position(signal, candle, candle_index, constraints, account, position)
        orders.append(order)
        fills.append(fill)
        trades.append(position.trade)
        return orders, fills, trades, warnings, None

    if signal.action is SignalAction.REVERSE:
        if position is not None:
            close_order, close_fill = _close_position(signal, candle, candle_index, constraints, account, position)
            orders.append(close_order)
            fills.append(close_fill)
            trades.append(position.trade)
            position = None
        open_order, open_fill, next_position = _open_position(signal, candle, candle_index, constraints, account)
        orders.append(open_order)
        if open_fill is not None:
            fills.append(open_fill)
        return orders, fills, trades, warnings, next_position

    return orders, fills, trades, warnings, position


def _open_position(
    signal: SignalIntent,
    candle: CanonicalCandle,
    candle_index: int,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
) -> tuple[OrderRequest, FillEvent | None, _OpenPosition | None]:
    qty = _resolve_order_qty(signal=signal, price=candle.open, constraints=constraints, account=account)
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
        entry_signal_meta_json=dict(signal.meta_json),
    )
    _apply_risk_spec_to_trade(trade=trade, signal=signal)
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
    return order, fill, _OpenPosition(trade=trade, reserved_margin=margin, entry_index=candle_index)


def _close_position(
    signal: SignalIntent,
    candle: CanonicalCandle,
    candle_index: int,
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
    trade.holding_bars = max(0, candle_index - position.entry_index)

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


def _maybe_close_for_planned_sltp(
    *,
    candle: CanonicalCandle,
    candle_index: int,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
    position: _OpenPosition,
) -> tuple[OrderRequest, FillEvent, _OpenPosition] | tuple[None, None, None]:
    trigger = _resolve_sltp_trigger(position.trade, candle)
    if trigger is None:
        return None, None, None
    reason_code, fill_price = trigger
    order, fill = _close_position_at_price(
        run_id=position.trade.run_id,
        signal_id=f"sltp:{position.trade.trade_id}:{candle.timestamp.isoformat()}",
        reason_code=reason_code,
        fill_price=fill_price,
        request_price=candle.open,
        request_time=candle.timestamp,
        candle_index=candle_index,
        constraints=constraints,
        account=account,
        position=position,
    )
    return order, fill, position


def _resolve_sltp_trigger(trade: TradeRecord, candle: CanonicalCandle) -> tuple[str, float] | None:
    stop = trade.planned_stop_loss_price
    take_profit = trade.planned_take_profit_price
    if stop is None and take_profit is None:
        return None

    if trade.side is Side.LONG:
        if stop is not None and candle.open <= stop:
            return "stop_loss_gap_open", candle.open
        if take_profit is not None and candle.open >= take_profit:
            return "take_profit_gap_open", candle.open
        if stop is not None and candle.low <= stop:
            return "stop_loss_intrabar", stop
        if take_profit is not None and candle.high >= take_profit:
            return "take_profit_intrabar", take_profit
        return None

    if trade.side is Side.SHORT:
        if stop is not None and candle.open >= stop:
            return "stop_loss_gap_open", candle.open
        if take_profit is not None and candle.open <= take_profit:
            return "take_profit_gap_open", candle.open
        if stop is not None and candle.high >= stop:
            return "stop_loss_intrabar", stop
        if take_profit is not None and candle.low <= take_profit:
            return "take_profit_intrabar", take_profit
        return None

    return None


def _close_position_at_price(
    *,
    run_id: str,
    signal_id: str,
    reason_code: str,
    fill_price: float,
    request_price: float,
    request_time,
    candle_index: int,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
    position: _OpenPosition,
) -> tuple[OrderRequest, FillEvent]:
    trade = position.trade
    fee = fill_price * trade.qty * constraints.fee_rate
    gross_pnl = _realized_pnl(trade.side, trade.entry_price, fill_price, trade.qty)
    net_pnl = gross_pnl - trade.fee - fee

    account.used_margin -= position.reserved_margin
    account.available_cash += position.reserved_margin + gross_pnl - fee
    account.equity = account.available_cash + account.used_margin
    account.unrealized_pnl = 0.0

    trade.exit_time = request_time
    trade.exit_price = fill_price
    trade.gross_pnl = gross_pnl
    trade.fee += fee
    trade.net_pnl = net_pnl
    trade.return_pct = gross_pnl / (trade.entry_price * trade.qty) if trade.entry_price > 0 and trade.qty > 0 else 0.0
    trade.exit_reason = reason_code
    trade.holding_bars = max(0, candle_index - position.entry_index)

    order = OrderRequest(
        order_id=_next_id("order"),
        run_id=run_id,
        signal_id=signal_id,
        symbol=trade.symbol,
        side=trade.side,
        order_type="market",
        qty=trade.qty,
        request_time=request_time,
        request_price=request_price,
        status="filled",
    )
    fill = FillEvent(
        fill_id=_next_id("fill"),
        run_id=run_id,
        order_id=order.order_id,
        trade_id=trade.trade_id,
        fill_time=request_time,
        fill_price=fill_price,
        qty=trade.qty,
        fee=fee,
        slippage_cost=abs(fill_price - request_price) * trade.qty,
    )
    return order, fill


def _apply_risk_spec_to_trade(*, trade: TradeRecord, signal: SignalIntent) -> None:
    risk_spec = signal.meta_json.get("risk_spec")
    if not isinstance(risk_spec, dict):
        return
    if risk_spec.get("stop_loss_mode") != "atr_multiple" or risk_spec.get("take_profit_mode") != "rr":
        return
    atr_value = _risk_spec_float(risk_spec.get("atr_value"), "atr_value")
    stop_mult = _risk_spec_float(risk_spec.get("stop_loss_value"), "stop_loss_value")
    reward_ratio = _risk_spec_float(risk_spec.get("take_profit_value"), "take_profit_value")
    min_stop_pct = _risk_spec_float(risk_spec.get("min_stop_pct"), "min_stop_pct")
    stop_distance = max(atr_value * stop_mult, trade.entry_price * min_stop_pct)
    if trade.side is Side.LONG:
        trade.planned_stop_loss_price = trade.entry_price - stop_distance
        trade.planned_take_profit_price = trade.entry_price + (stop_distance * reward_ratio)
    elif trade.side is Side.SHORT:
        trade.planned_stop_loss_price = trade.entry_price + stop_distance
        trade.planned_take_profit_price = trade.entry_price - (stop_distance * reward_ratio)


def _risk_spec_float(value: object, field_name: Literal["atr_value", "stop_loss_value", "take_profit_value", "min_stop_pct"]) -> float:
    if not isinstance(value, int | float):
        raise ValueError(f"risk_spec requires numeric {field_name}")
    numeric = float(value)
    if numeric < 0:
        raise ValueError(f"risk_spec {field_name} must be >= 0")
    return numeric


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
    required_cash = required_margin + estimated_fee
    tolerance = max(_MARGIN_CHECK_ABS_TOLERANCE, abs(required_cash) * _MARGIN_CHECK_REL_TOLERANCE)
    if account.available_cash + tolerance < required_cash:
        return RejectReasonCode.INSUFFICIENT_MARGIN
    return None


def _resolve_order_qty(
    *,
    signal: SignalIntent,
    price: float,
    constraints: ExecutionConstraints,
    account: AccountSnapshot,
) -> float:
    cash_allocation_pct = constraints.cash_allocation_pct_by_policy.get(signal.qty_policy_ref)
    risk_pct_per_trade = constraints.risk_pct_per_trade_by_policy.get(signal.qty_policy_ref)
    if risk_pct_per_trade is not None:
        stop_distance = _planned_stop_distance_from_signal(signal=signal, entry_price=price)
        if stop_distance is None:
            return 0.0
        if cash_allocation_pct is not None:
            return _qty_from_cash_allocation_risk(
                price=price,
                leverage=constraints.leverage,
                fee_rate=constraints.fee_rate,
                available_cash=account.available_cash,
                cash_allocation_pct=cash_allocation_pct,
                stop_distance=stop_distance,
                risk_pct_per_trade=risk_pct_per_trade,
            )
        return _qty_from_risk_pct_of_equity(
            price=price,
            leverage=constraints.leverage,
            fee_rate=constraints.fee_rate,
            available_cash=account.available_cash,
            account_equity=account.equity,
            stop_distance=stop_distance,
            risk_pct_per_trade=risk_pct_per_trade,
        )
    if cash_allocation_pct is not None:
        return _qty_from_cash_allocation(
            price=price,
            leverage=constraints.leverage,
            fee_rate=constraints.fee_rate,
            available_cash=account.available_cash,
            cash_allocation_pct=cash_allocation_pct,
        )
    return constraints.qty_by_policy.get(signal.qty_policy_ref, 0.0)


def _qty_from_cash_allocation(
    *,
    price: float,
    leverage: float,
    fee_rate: float,
    available_cash: float,
    cash_allocation_pct: float,
) -> float:
    if price <= 0:
        return 0.0
    allocated_cash = available_cash * (cash_allocation_pct / 100)
    if allocated_cash <= 0:
        return 0.0
    notional_cost_per_unit = (1 / leverage) + fee_rate
    if notional_cost_per_unit <= 0:
        return 0.0
    notional = allocated_cash / notional_cost_per_unit
    return notional / price


def _qty_from_risk_pct_of_equity(
    *,
    price: float,
    leverage: float,
    fee_rate: float,
    available_cash: float,
    account_equity: float,
    stop_distance: float,
    risk_pct_per_trade: float,
) -> float:
    if price <= 0 or stop_distance <= 0 or account_equity <= 0:
        return 0.0
    risk_cash = account_equity * risk_pct_per_trade
    if risk_cash <= 0:
        return 0.0
    qty_from_risk = risk_cash / stop_distance
    qty_from_margin = _qty_from_cash_allocation(
        price=price,
        leverage=leverage,
        fee_rate=fee_rate,
        available_cash=available_cash,
        cash_allocation_pct=100.0,
    )
    if qty_from_margin <= 0:
        return 0.0
    return min(qty_from_risk, qty_from_margin)


def _qty_from_cash_allocation_risk(
    *,
    price: float,
    leverage: float,
    fee_rate: float,
    available_cash: float,
    cash_allocation_pct: float,
    stop_distance: float,
    risk_pct_per_trade: float,
) -> float:
    if price <= 0 or stop_distance <= 0 or available_cash <= 0:
        return 0.0
    allocated_cash = available_cash * (cash_allocation_pct / 100)
    if allocated_cash <= 0:
        return 0.0
    risk_cash = allocated_cash * risk_pct_per_trade
    if risk_cash <= 0:
        return 0.0
    qty_from_risk = risk_cash / stop_distance
    qty_from_allocation = _qty_from_cash_allocation(
        price=price,
        leverage=leverage,
        fee_rate=fee_rate,
        available_cash=available_cash,
        cash_allocation_pct=cash_allocation_pct,
    )
    if qty_from_allocation <= 0:
        return 0.0
    return min(qty_from_risk, qty_from_allocation)


def _planned_stop_distance_from_signal(*, signal: SignalIntent, entry_price: float) -> float | None:
    risk_spec = signal.meta_json.get("risk_spec")
    if not isinstance(risk_spec, dict):
        return None
    if risk_spec.get("stop_loss_mode") != "atr_multiple" or risk_spec.get("take_profit_mode") != "rr":
        return None
    atr_value = _risk_spec_float(risk_spec.get("atr_value"), "atr_value")
    stop_mult = _risk_spec_float(risk_spec.get("stop_loss_value"), "stop_loss_value")
    min_stop_pct = _risk_spec_float(risk_spec.get("min_stop_pct"), "min_stop_pct")
    return max(atr_value * stop_mult, entry_price * min_stop_pct)


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
