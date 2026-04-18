"""Reference EMA crossover strategy for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.domain.models import FeatureSpec, Side, SignalAction, SignalIntent

from .base import StrategyDefinition, StrategyInput
from .reader import load_feature_rows


@dataclass(slots=True)
class EMACrossoverStrategy(StrategyDefinition):
    """Generate directional signals from two precomputed EMA columns."""

    fast_period: int = 12
    slow_period: int = 26
    input_price_field: str = "close"
    qty_policy_ref: str = "fixed_notional_v1"
    feature_version: str = "ema_v1"
    name: str = "ema_crossover"
    version: str = "v1"

    def __post_init__(self) -> None:
        if self.fast_period <= 0 or self.slow_period <= 0:
            raise ValueError("EMA periods must be positive integers.")
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be smaller than slow_period.")

    @property
    def fast_column(self) -> str:
        return f"ema_{self.input_price_field}_{self.fast_period}"

    @property
    def slow_column(self) -> str:
        return f"ema_{self.input_price_field}_{self.slow_period}"

    def feature_specs(self) -> tuple[FeatureSpec, ...]:
        warmup_bars = self.slow_period + 1
        return (
            FeatureSpec(
                name="ema",
                params={"window": self.fast_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
            FeatureSpec(
                name="ema",
                params={"window": self.slow_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
        )

    def generate_signals(self, data: StrategyInput) -> list[SignalIntent]:
        rows = load_feature_rows(
            data.features_uri,
            required_columns=("timestamp", self.fast_column, self.slow_column),
        )
        if len(rows) < 2:
            return []

        signals: list[SignalIntent] = []
        desired_side = Side.FLAT

        for index in range(1, len(rows)):
            previous = rows[index - 1]
            current = rows[index]
            prev_fast = previous.values[self.fast_column]
            prev_slow = previous.values[self.slow_column]
            curr_fast = current.values[self.fast_column]
            curr_slow = current.values[self.slow_column]

            if None in {prev_fast, prev_slow, curr_fast, curr_slow}:
                continue

            if prev_fast <= prev_slow and curr_fast > curr_slow:
                if desired_side != Side.LONG:
                    action = SignalAction.OPEN if desired_side == Side.FLAT else SignalAction.REVERSE
                    signals.append(
                        self._build_signal(
                            data=data,
                            signal_index=len(signals),
                            timestamp=current.timestamp,
                            action=action,
                            side=Side.LONG,
                            reason_code="ema_bullish_crossover",
                            fast_value=curr_fast,
                            slow_value=curr_slow,
                        )
                    )
                    desired_side = Side.LONG
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                if desired_side != Side.SHORT:
                    action = SignalAction.OPEN if desired_side == Side.FLAT else SignalAction.REVERSE
                    signals.append(
                        self._build_signal(
                            data=data,
                            signal_index=len(signals),
                            timestamp=current.timestamp,
                            action=action,
                            side=Side.SHORT,
                            reason_code="ema_bearish_crossover",
                            fast_value=curr_fast,
                            slow_value=curr_slow,
                        )
                    )
                    desired_side = Side.SHORT

        return signals

    def _build_signal(
        self,
        *,
        data: StrategyInput,
        signal_index: int,
        timestamp,
        action: SignalAction,
        side: Side,
        reason_code: str,
        fast_value: float,
        slow_value: float,
    ) -> SignalIntent:
        score = abs(fast_value - slow_value)
        return SignalIntent(
            signal_id=f"{data.run_id}:{self.name}:{signal_index}",
            run_id=data.run_id,
            timestamp=timestamp,
            symbol=data.symbol,
            action=action,
            side=side,
            qty_policy_ref=str(data.config.get("qty_policy_ref", self.qty_policy_ref)),
            reason_code=reason_code,
            signal_score=score,
            meta_json={
                "feature_artifact_id": data.feature_artifact_id,
                "fast_column": self.fast_column,
                "slow_column": self.slow_column,
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "fast_value": fast_value,
                "slow_value": slow_value,
            },
        )
