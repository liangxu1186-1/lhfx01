"""EMA pullback ATR strategy v2."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_backtest_workbench.domain.models import FeatureSpec, Side, SignalAction, SignalIntent

from .base import StrategyDefinition, StrategyInput
from .reader import load_feature_rows


@dataclass(slots=True)
class EMAPullbackATRStrategy(StrategyDefinition):
    trend_fast_period: int
    trend_slow_period: int
    atr_entry_tolerance: float
    atr_stop_mult: float
    risk_reward_ratio: float
    entry_ema_period: int = 21
    atr_period: int = 14
    min_atr_pct_of_price: float = 0.002
    min_stop_pct: float = 0.003
    qty_policy_ref: str = "percent_of_cash"
    cash_allocation_pct: float | None = None
    risk_pct_per_trade: float | None = None
    signal_filters: tuple[dict[str, object], ...] = ()
    input_price_field: str = "close"
    name: str = "ema_pullback_atr_v2"
    version: str = "v2"

    def __post_init__(self) -> None:
        for field_name in ("trend_fast_period", "trend_slow_period", "entry_ema_period", "atr_period"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.trend_fast_period >= self.trend_slow_period:
            raise ValueError("trend_fast_period must be smaller than trend_slow_period")
        if self.atr_entry_tolerance < 0:
            raise ValueError("atr_entry_tolerance must be >= 0")
        if self.atr_stop_mult <= 0:
            raise ValueError("atr_stop_mult must be greater than 0")
        if self.risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be greater than 0")
        if self.min_atr_pct_of_price < 0:
            raise ValueError("min_atr_pct_of_price must be >= 0")
        if self.min_stop_pct < 0:
            raise ValueError("min_stop_pct must be >= 0")
        if self.cash_allocation_pct is not None and (self.cash_allocation_pct <= 0 or self.cash_allocation_pct > 100):
            raise ValueError("cash_allocation_pct must be in (0, 100]")
        if self.risk_pct_per_trade is not None and (self.risk_pct_per_trade <= 0 or self.risk_pct_per_trade >= 1):
            raise ValueError("risk_pct_per_trade must be in (0, 1)")
        self.signal_filters = tuple(self.signal_filters or ())

    @property
    def trend_fast_column(self) -> str:
        return f"ema_{self.input_price_field}_{self.trend_fast_period}"

    @property
    def trend_slow_column(self) -> str:
        return f"ema_{self.input_price_field}_{self.trend_slow_period}"

    @property
    def entry_ema_column(self) -> str:
        return f"ema_{self.input_price_field}_{self.entry_ema_period}"

    @property
    def atr_column(self) -> str:
        return f"atr_{self.atr_period}"

    @property
    def warmup_bars(self) -> int:
        return max(self.trend_slow_period, self.entry_ema_period, self.atr_period) + 20

    def feature_specs(self) -> tuple[FeatureSpec, ...]:
        warmup_bars = self.warmup_bars
        specs: list[FeatureSpec] = [
            FeatureSpec(
                name="ema",
                params={"window": self.trend_fast_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
            FeatureSpec(
                name="ema",
                params={"window": self.trend_slow_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
            FeatureSpec(
                name="ema",
                params={"window": self.entry_ema_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
            FeatureSpec(
                name="atr",
                params={"window": self.atr_period},
                input_price_field=self.input_price_field,
                warmup_bars=warmup_bars,
            ),
        ]
        for signal_filter in self.signal_filters:
            filter_type = str(signal_filter.get("filter_type", ""))
            params = signal_filter.get("params")
            filter_params = params if isinstance(params, dict) else {}
            if filter_type == "higher_timeframe_trend":
                ema_fast = int(filter_params.get("ema_fast", self.trend_fast_period))
                ema_slow = int(filter_params.get("ema_slow", self.trend_slow_period))
                specs.extend(
                    [
                        FeatureSpec(name="ema", params={"window": ema_fast}, input_price_field=self.input_price_field, warmup_bars=max(warmup_bars, ema_slow)),
                        FeatureSpec(name="ema", params={"window": ema_slow}, input_price_field=self.input_price_field, warmup_bars=max(warmup_bars, ema_slow)),
                    ]
                )
            elif filter_type == "atr_percentile":
                atr_period = int(filter_params.get("atr_period", self.atr_period))
                lookback_bars = int(filter_params.get("lookback_bars", 200))
                specs.append(
                    FeatureSpec(name="atr", params={"window": atr_period}, input_price_field=self.input_price_field, warmup_bars=max(warmup_bars, atr_period + lookback_bars))
                )
            elif filter_type == "adx":
                adx_period = int(filter_params.get("adx_period", 14))
                specs.append(
                    FeatureSpec(name="adx", params={"window": adx_period}, input_price_field=self.input_price_field, warmup_bars=max(warmup_bars, adx_period * 2))
                )
            else:
                raise ValueError(f"Unsupported signal filter type: {filter_type}")
        return tuple(_dedupe_feature_specs(specs))

    def generate_signals(self, data: StrategyInput) -> list[SignalIntent]:
        required_columns = [
            "timestamp",
            "high",
            "low",
            "close",
            self.trend_fast_column,
            self.trend_slow_column,
            self.entry_ema_column,
            self.atr_column,
        ]
        required_columns.extend(_filter_required_columns(self.signal_filters, input_price_field=self.input_price_field, default_atr_period=self.atr_period))
        rows = load_feature_rows(data.features_uri, required_columns=tuple(dict.fromkeys(required_columns)))
        if len(rows) < 2:
            return []

        signals: list[SignalIntent] = []
        for index in range(1, len(rows)):
            previous = rows[index - 1]
            current = rows[index]
            values = current.values
            required_values = [
                values[self.trend_fast_column],
                values[self.trend_slow_column],
                values[self.entry_ema_column],
                values[self.atr_column],
                values["high"],
                values["low"],
                values["close"],
                previous.values["high"],
                previous.values["low"],
            ]
            if any(value is None for value in required_values):
                continue

            trend_fast = float(values[self.trend_fast_column])
            trend_slow = float(values[self.trend_slow_column])
            entry_ema = float(values[self.entry_ema_column])
            atr = float(values[self.atr_column])
            high = float(values["high"])
            low = float(values["low"])
            close = float(values["close"])
            previous_high = float(previous.values["high"])
            previous_low = float(previous.values["low"])
            if close <= 0 or atr / close < self.min_atr_pct_of_price:
                continue

            if (
                trend_fast > trend_slow
                and abs(low - entry_ema) <= atr * self.atr_entry_tolerance
                and close > previous_high
            ):
                if not self._filters_allow_signal(rows=rows, index=index, side=Side.LONG):
                    continue
                signals.append(
                    self._build_signal(
                        data=data,
                        signal_index=len(signals),
                        timestamp=current.timestamp,
                        side=Side.LONG,
                        reason_code="ema_pullback_atr_long_breakout",
                        feature_values={
                            "trend_fast_ema": trend_fast,
                            "trend_slow_ema": trend_slow,
                            "entry_ema": entry_ema,
                            "atr": atr,
                            "low": low,
                            "close": close,
                            "previous_high": previous_high,
                        },
                    )
                )
            elif (
                trend_fast < trend_slow
                and abs(high - entry_ema) <= atr * self.atr_entry_tolerance
                and close < previous_low
            ):
                if not self._filters_allow_signal(rows=rows, index=index, side=Side.SHORT):
                    continue
                signals.append(
                    self._build_signal(
                        data=data,
                        signal_index=len(signals),
                        timestamp=current.timestamp,
                        side=Side.SHORT,
                        reason_code="ema_pullback_atr_short_breakdown",
                        feature_values={
                            "trend_fast_ema": trend_fast,
                            "trend_slow_ema": trend_slow,
                            "entry_ema": entry_ema,
                            "atr": atr,
                            "high": high,
                            "close": close,
                            "previous_low": previous_low,
                        },
                    )
                )

        return signals

    def _build_signal(
        self,
        *,
        data: StrategyInput,
        signal_index: int,
        timestamp,
        side: Side,
        reason_code: str,
        feature_values: dict[str, float],
    ) -> SignalIntent:
        atr = feature_values["atr"]
        return SignalIntent(
            signal_id=f"{data.run_id}:{self.name}:{signal_index}",
            run_id=data.run_id,
            timestamp=timestamp,
            symbol=data.symbol,
            action=SignalAction.OPEN,
            side=side,
            qty_policy_ref=str(data.config.get("qty_policy_ref", self.qty_policy_ref)),
            reason_code=reason_code,
            signal_score=atr,
            meta_json={
                "feature_artifact_id": data.feature_artifact_id,
                "strategy_params": self.strategy_params(),
                "feature_values": feature_values,
                "risk_spec": {
                    "stop_loss_mode": "atr_multiple",
                    "stop_loss_value": self.atr_stop_mult,
                    "take_profit_mode": "rr",
                    "take_profit_value": self.risk_reward_ratio,
                    "atr_value": atr,
                    "min_stop_pct": self.min_stop_pct,
                },
            },
        )

    def _filters_allow_signal(self, *, rows, index: int, side: Side) -> bool:
        if not self.signal_filters:
            return True
        for signal_filter in self.signal_filters:
            if signal_filter.get("enabled") is False:
                continue
            filter_type = str(signal_filter.get("filter_type", ""))
            params = signal_filter.get("params")
            filter_params = params if isinstance(params, dict) else {}
            if filter_type == "higher_timeframe_trend":
                if not _higher_timeframe_trend_allows(rows[index].values, filter_params, side=side, input_price_field=self.input_price_field):
                    return False
            elif filter_type == "atr_percentile":
                if not _atr_percentile_allows(rows=rows, index=index, filter_params=filter_params, default_atr_period=self.atr_period):
                    return False
            elif filter_type == "adx":
                if not _adx_allows(rows[index].values, filter_params):
                    return False
            else:
                raise ValueError(f"Unsupported signal filter type: {filter_type}")
        return True

    def strategy_params(self) -> dict[str, object]:
        params: dict[str, object] = {
            "trend_fast_period": self.trend_fast_period,
            "trend_slow_period": self.trend_slow_period,
            "atr_entry_tolerance": self.atr_entry_tolerance,
            "atr_stop_mult": self.atr_stop_mult,
            "risk_reward_ratio": self.risk_reward_ratio,
            "entry_ema_period": self.entry_ema_period,
            "atr_period": self.atr_period,
            "min_atr_pct_of_price": self.min_atr_pct_of_price,
            "min_stop_pct": self.min_stop_pct,
            "qty_policy_ref": self.qty_policy_ref,
            "cash_allocation_pct": self.cash_allocation_pct,
            "risk_pct_per_trade": self.risk_pct_per_trade,
        }
        if self.signal_filters:
            params["signal_filters"] = list(self.signal_filters)
        return params


def _dedupe_feature_specs(specs: list[FeatureSpec]) -> list[FeatureSpec]:
    seen: set[tuple[object, ...]] = set()
    result: list[FeatureSpec] = []
    for spec in specs:
        key = (spec.name, spec.input_price_field, tuple(sorted(spec.params.items())))
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
    return result


def _filter_required_columns(signal_filters: tuple[dict[str, object], ...], *, input_price_field: str, default_atr_period: int) -> list[str]:
    columns: list[str] = []
    for signal_filter in signal_filters:
        if signal_filter.get("enabled") is False:
            continue
        filter_type = str(signal_filter.get("filter_type", ""))
        params = signal_filter.get("params")
        filter_params = params if isinstance(params, dict) else {}
        if filter_type == "higher_timeframe_trend":
            columns.append(f"ema_{input_price_field}_{int(filter_params.get('ema_fast', 50))}")
            columns.append(f"ema_{input_price_field}_{int(filter_params.get('ema_slow', 200))}")
        elif filter_type == "atr_percentile":
            columns.append(f"atr_{int(filter_params.get('atr_period', default_atr_period))}")
        elif filter_type == "adx":
            columns.append(f"adx_{int(filter_params.get('adx_period', 14))}")
    return columns


def _higher_timeframe_trend_allows(values: dict[str, object], filter_params: dict[str, object], *, side: Side, input_price_field: str) -> bool:
    ema_fast = int(filter_params.get("ema_fast", 50))
    ema_slow = int(filter_params.get("ema_slow", 200))
    mode = str(filter_params.get("mode", "direction_aligned"))
    fast_value = values.get(f"ema_{input_price_field}_{ema_fast}")
    slow_value = values.get(f"ema_{input_price_field}_{ema_slow}")
    close_value = values.get("close")
    if slow_value is None:
        return False
    slow = float(slow_value)
    if mode == "close_above_ema":
        if close_value is None:
            return False
        close = float(close_value)
        return close >= slow if side is Side.LONG else close <= slow
    if fast_value is None:
        return False
    fast = float(fast_value)
    if mode in {"ema_fast_above_slow", "direction_aligned"}:
        return fast >= slow if side is Side.LONG else fast <= slow
    raise ValueError(f"Unsupported higher_timeframe_trend mode: {mode}")


def _atr_percentile_allows(*, rows, index: int, filter_params: dict[str, object], default_atr_period: int) -> bool:
    atr_period = int(filter_params.get("atr_period", default_atr_period))
    lookback_bars = int(filter_params.get("lookback_bars", 200))
    min_percentile = _optional_float(filter_params.get("min_percentile"))
    max_percentile = _optional_float(filter_params.get("max_percentile"))
    if lookback_bars <= 1:
        raise ValueError("atr_percentile lookback_bars must be greater than 1")
    column = f"atr_{atr_period}"
    current = rows[index].values.get(column)
    if current is None:
        return False
    start = max(0, index - lookback_bars)
    history = [
        float(row.values[column])
        for row in rows[start:index]
        if row.values.get(column) is not None
    ]
    if len(history) < max(10, min(lookback_bars // 2, 50)):
        return False
    current_value = float(current)
    rank = sum(1 for value in history if value <= current_value) / len(history) * 100.0
    if min_percentile is not None and rank < min_percentile:
        return False
    if max_percentile is not None and rank > max_percentile:
        return False
    return True


def _adx_allows(values: dict[str, object], filter_params: dict[str, object]) -> bool:
    adx_period = int(filter_params.get("adx_period", 14))
    min_adx = _optional_float(filter_params.get("min_adx"))
    max_adx = _optional_float(filter_params.get("max_adx"))
    value = values.get(f"adx_{adx_period}")
    if value is None:
        return False
    adx = float(value)
    if min_adx is not None and adx < min_adx:
        return False
    if max_adx is not None and adx > max_adx:
        return False
    return True


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
