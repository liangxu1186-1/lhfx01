"""Incremental paper broker using the backtest execution semantics."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.app.paper_trading.models import PaperPosition, PaperSession
from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    FillEvent,
    OrderRequest,
    SignalAction,
    SignalIntent,
    StructuredWarning,
    TradeRecord,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.execution.simulator import (
    _OpenPosition,
    _execute_signal,
    _maybe_close_for_planned_sltp,
    _unrealized_pnl,
)


@dataclass(slots=True)
class PaperBrokerResult:
    orders: list[OrderRequest]
    fills: list[FillEvent]
    trades: list[TradeRecord]
    warnings: list[StructuredWarning]
    position: PaperPosition | None


class PaperBroker:
    """Process newly closed execution bars against a persisted paper session."""

    def execute(
        self,
        *,
        session: PaperSession,
        execution_candles: list[CanonicalCandle],
        signals: list[SignalIntent],
        constraints: ExecutionConstraints,
    ) -> PaperBrokerResult:
        sorted_candles = sorted(execution_candles, key=lambda candle: candle.timestamp)
        sorted_signals = sorted(signals, key=lambda signal: signal.timestamp)
        if not sorted_candles:
            return PaperBrokerResult([], [], [], [], session.position)

        orders: list[OrderRequest] = []
        fills: list[FillEvent] = []
        trades: list[TradeRecord] = []
        warnings: list[StructuredWarning] = []
        position = _to_open_position(session.position)
        signal_cursor = 0
        executed_signal_ids: set[str] = set()
        base_index = session.checkpoint.execution_bar_count

        for local_index, candle in enumerate(sorted_candles):
            execution_index = base_index + local_index
            if position is not None:
                sltp_order, sltp_fill, closed_position = _maybe_close_for_planned_sltp(
                    candle=candle,
                    candle_index=execution_index,
                    constraints=constraints,
                    account=session.account,
                    position=position,
                )
                if closed_position is not None:
                    orders.append(sltp_order)
                    fills.append(sltp_fill)
                    trades.append(closed_position.trade)
                    position = None

            due_signals: list[SignalIntent] = []
            while signal_cursor < len(sorted_signals) and _signal_is_due(sorted_signals[signal_cursor], candle):
                signal = sorted_signals[signal_cursor]
                signal_cursor += 1
                if signal.signal_id in executed_signal_ids:
                    continue
                due_signals.append(signal)
                executed_signal_ids.add(signal.signal_id)

            for signal in due_signals:
                if signal.action is SignalAction.HOLD:
                    continue
                signal_orders, signal_fills, signal_trades, signal_warnings, position = _execute_signal(
                    signal=signal,
                    candle=candle,
                    candle_index=execution_index,
                    constraints=constraints,
                    account=session.account,
                    position=position,
                )
                orders.extend(signal_orders)
                fills.extend(signal_fills)
                trades.extend(signal_trades)
                warnings.extend(signal_warnings)
                if position is not None and position.trade.entry_time == candle.timestamp:
                    sltp_order, sltp_fill, closed_position = _maybe_close_for_planned_sltp(
                        candle=candle,
                        candle_index=execution_index,
                        constraints=constraints,
                        account=session.account,
                        position=position,
                    )
                    if closed_position is not None:
                        orders.append(sltp_order)
                        fills.append(sltp_fill)
                        trades.append(closed_position.trade)
                        position = None

            session.account.unrealized_pnl = _unrealized_pnl(position, candle.close)
            session.account.equity = session.account.available_cash + session.account.used_margin + session.account.unrealized_pnl

        return PaperBrokerResult(
            orders=orders,
            fills=fills,
            trades=trades,
            warnings=warnings,
            position=_from_open_position(position) if position is not None else None,
        )


def _to_open_position(position: PaperPosition | None) -> _OpenPosition | None:
    if position is None:
        return None
    return _OpenPosition(
        trade=position.trade,
        reserved_margin=position.reserved_margin,
        entry_index=position.entry_execution_index,
    )


def _signal_is_due(signal: SignalIntent, candle: CanonicalCandle) -> bool:
    if signal.timestamp < candle.timestamp:
        return True
    if signal.timestamp != candle.timestamp:
        return False
    return signal.meta_json.get("execution_signal_timestamp") == candle.timestamp.isoformat()


def _from_open_position(position: _OpenPosition) -> PaperPosition:
    return PaperPosition(
        trade=position.trade,
        reserved_margin=position.reserved_margin,
        entry_execution_index=position.entry_index,
    )
