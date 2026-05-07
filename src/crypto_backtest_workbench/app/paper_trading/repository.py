"""Filesystem persistence for paper-trading sessions."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from crypto_backtest_workbench.app.paper_trading.models import (
    PaperCheckpoint,
    PaperPosition,
    PaperSession,
)
from crypto_backtest_workbench.app.paper_trading.serialization import json_ready
from crypto_backtest_workbench.domain.models import (
    FillEvent,
    OrderRequest,
    RejectReasonCode,
    Side,
    SignalAction,
    StructuredWarning,
    TradeRecord,
    WarningType,
)
from crypto_backtest_workbench.engine.portfolio.account import AccountSnapshot


class FilePaperTradingRepository:
    """Store paper sessions under data/paper_trading."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def list_sessions(self) -> list[PaperSession]:
        root = self._root()
        if not root.exists():
            return []
        sessions: list[PaperSession] = []
        for path in sorted(root.rglob("session.json")):
            sessions.append(_paper_session_from_json(json.loads(path.read_text(encoding="utf-8"))))
        return sessions

    def save_session(self, session: PaperSession) -> Path:
        directory = self._session_dir(session.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "session.json"
        path.write_text(json.dumps(json_ready(session), indent=2, sort_keys=True), encoding="utf-8")
        return path

    def load_session(self, session_id: str) -> PaperSession:
        path = self._session_dir(session_id) / "session.json"
        if not path.exists():
            path = self._find_session_json(session_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _paper_session_from_json(payload)

    def append_orders(self, session_id: str, orders: Iterable[OrderRequest]) -> Path:
        return self._append_csv(session_id, "orders.csv", orders)

    def append_fills(self, session_id: str, fills: Iterable[FillEvent]) -> Path:
        return self._append_csv(session_id, "fills.csv", fills)

    def append_trades(self, session_id: str, trades: Iterable[TradeRecord]) -> Path:
        return self._append_csv(session_id, "trades.csv", trades)

    def append_warnings(self, session_id: str, warnings: Iterable[StructuredWarning]) -> Path:
        return self._append_csv(session_id, "warnings.csv", warnings)

    def _append_csv(self, session_id: str, file_name: str, rows: Iterable[object]) -> Path:
        payloads = [json_ready(row) for row in rows]
        path = self._session_dir(session_id) / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not payloads:
            return path
        fieldnames: list[str] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in payload:
                if key not in fieldnames:
                    fieldnames.append(key)
        exists = path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if not exists:
                writer.writeheader()
            for payload in payloads:
                if isinstance(payload, dict):
                    writer.writerow({key: _csv_cell(payload.get(key)) for key in fieldnames})
        return path

    def _root(self) -> Path:
        return self.base_dir / "paper_trading" / "sessions"

    def _session_dir(self, session_id: str) -> Path:
        return self._root() / _safe_path_part(session_id)

    def _find_session_json(self, session_id: str) -> Path:
        root = self._root()
        for path in root.rglob("session.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if str(payload.get("session_id") or "") == session_id:
                return path
        raise FileNotFoundError(f"Paper session not found: {session_id}")


def _paper_session_from_json(payload: dict[str, object]) -> PaperSession:
    checkpoint_payload = _dict(payload.get("checkpoint"))
    position_payload = payload.get("position")
    account_payload = _dict(payload["account"])
    return PaperSession(
        session_id=str(payload["session_id"]),
        stable_candidate_id=str(payload["stable_candidate_id"]),
        source_run_id=str(payload["source_run_id"]),
        strategy_name=str(payload["strategy_name"]),
        symbol=str(payload["symbol"]),
        exchange=str(payload["exchange"]),
        market_type=str(payload["market_type"]),
        price_type=str(payload["price_type"]),
        strategy_timeframe=str(payload["strategy_timeframe"]),
        execution_timeframe=str(payload["execution_timeframe"]),
        strategy_params=_dict(payload["strategy_params"]),
        execution_constraints=_dict(payload["execution_constraints"]),
        account=AccountSnapshot(
            available_cash=float(account_payload["available_cash"]),
            used_margin=float(account_payload["used_margin"]),
            maintenance_margin=float(account_payload.get("maintenance_margin", 0.0)),
            equity=float(account_payload["equity"]),
            unrealized_pnl=float(account_payload.get("unrealized_pnl", 0.0)),
        ),
        checkpoint=PaperCheckpoint(
            last_strategy_bar_time=_parse_optional_datetime(checkpoint_payload.get("last_strategy_bar_time")),
            last_execution_bar_time=_parse_optional_datetime(checkpoint_payload.get("last_execution_bar_time")),
            last_signal_time=_parse_optional_datetime(checkpoint_payload.get("last_signal_time")),
            execution_bar_count=int(checkpoint_payload.get("execution_bar_count", 0)),
        ),
        position=_paper_position_from_json(_dict(position_payload)) if isinstance(position_payload, dict) else None,
        status=str(payload.get("status", "active")),
        created_at=_parse_datetime(str(payload["created_at"])),
        updated_at=_parse_datetime(str(payload["updated_at"])),
        model_version=str(payload.get("model_version", "paper-trading-v1")),
    )


def _paper_position_from_json(payload: dict[str, object]) -> PaperPosition:
    return PaperPosition(
        trade=_trade_from_json(_dict(payload["trade"])),
        reserved_margin=float(payload["reserved_margin"]),
        entry_execution_index=int(payload["entry_execution_index"]),
    )


def _trade_from_json(payload: dict[str, object]) -> TradeRecord:
    return TradeRecord(
        trade_id=str(payload["trade_id"]),
        run_id=str(payload["run_id"]),
        symbol=str(payload["symbol"]),
        side=Side(str(payload["side"])),
        entry_time=_parse_datetime(str(payload["entry_time"])),
        entry_price=float(payload["entry_price"]),
        exit_time=_parse_optional_datetime(payload.get("exit_time")),
        exit_price=_optional_float(payload.get("exit_price")),
        qty=float(payload["qty"]),
        gross_pnl=float(payload.get("gross_pnl", 0.0)),
        fee=float(payload.get("fee", 0.0)),
        net_pnl=float(payload.get("net_pnl", 0.0)),
        return_pct=float(payload.get("return_pct", 0.0)),
        holding_bars=int(payload.get("holding_bars", 0)),
        entry_reason=str(payload.get("entry_reason", "")),
        exit_reason=str(payload.get("exit_reason", "")),
        planned_stop_loss_price=_optional_float(payload.get("planned_stop_loss_price")),
        planned_take_profit_price=_optional_float(payload.get("planned_take_profit_price")),
        entry_signal_meta_json=_dict(payload.get("entry_signal_meta_json")),
    )


def _parse_datetime(value: str):
    from datetime import UTC, datetime

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: object) -> object:
    if value in {None, ""}:
        return None
    return _parse_datetime(str(value))


def _optional_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _csv_cell(value: object) -> object:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


def _safe_path_part(value: str) -> str:
    chars = [char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value]
    compact = "-".join(part for part in "".join(chars).split("-") if part)
    return compact[:180] or "paper-session"
