"""Account and portfolio snapshots."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AccountSnapshot:
    available_cash: float
    used_margin: float
    maintenance_margin: float
    equity: float
    unrealized_pnl: float = 0.0

    def has_margin_for(self, required_margin: float) -> bool:
        return self.available_cash >= required_margin

