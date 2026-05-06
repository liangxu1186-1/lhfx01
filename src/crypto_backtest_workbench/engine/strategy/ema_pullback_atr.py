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
            elif filter_type in {"pre_entry_momentum", "consecutive_move", "local_range_position", "entry_context_exclusion"}:
                continue
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
                feature_values = {
                    "trend_fast_ema": trend_fast,
                    "trend_slow_ema": trend_slow,
                    "entry_ema": entry_ema,
                    "atr": atr,
                    "low": low,
                    "close": close,
                    "previous_high": previous_high,
                }
                feature_values.update(self._entry_context_features(rows=rows, index=index, side=Side.LONG, base_features=feature_values))
                if not self._filters_allow_signal(rows=rows, index=index, side=Side.LONG, feature_values=feature_values):
                    continue
                signals.append(
                    self._build_signal(
                        data=data,
                        signal_index=len(signals),
                        timestamp=current.timestamp,
                        side=Side.LONG,
                        reason_code="ema_pullback_atr_long_breakout",
                        feature_values=feature_values,
                    )
                )
            elif (
                trend_fast < trend_slow
                and abs(high - entry_ema) <= atr * self.atr_entry_tolerance
                and close < previous_low
            ):
                feature_values = {
                    "trend_fast_ema": trend_fast,
                    "trend_slow_ema": trend_slow,
                    "entry_ema": entry_ema,
                    "atr": atr,
                    "high": high,
                    "close": close,
                    "previous_low": previous_low,
                }
                feature_values.update(self._entry_context_features(rows=rows, index=index, side=Side.SHORT, base_features=feature_values))
                if not self._filters_allow_signal(rows=rows, index=index, side=Side.SHORT, feature_values=feature_values):
                    continue
                signals.append(
                    self._build_signal(
                        data=data,
                        signal_index=len(signals),
                        timestamp=current.timestamp,
                        side=Side.SHORT,
                        reason_code="ema_pullback_atr_short_breakdown",
                        feature_values=feature_values,
                    )
                )

        return signals

    def _entry_context_features(self, *, rows, index: int, side: Side, base_features: dict[str, float]) -> dict[str, float]:
        current = rows[index]
        previous = rows[:index]
        values = current.values
        close_value = values.get("close")
        if close_value is None:
            return {}
        close = float(close_value)
        atr = base_features.get("atr")
        trend_fast = base_features.get("trend_fast_ema")
        trend_slow = base_features.get("trend_slow_ema")
        entry_ema = base_features.get("entry_ema")
        result: dict[str, float] = {}
        if close > 0 and atr is not None:
            result["atr_pct"] = atr / close
        if close > 0 and trend_fast is not None and trend_slow is not None:
            result["trend_gap_pct"] = abs(trend_fast - trend_slow) / close
        if atr and atr > 0 and trend_fast is not None and trend_slow is not None:
            result["trend_gap_atr"] = abs(trend_fast - trend_slow) / atr
        if atr and atr > 0 and entry_ema is not None:
            touch_value = values.get("low") if side is Side.LONG else values.get("high")
            if touch_value is not None:
                result["entry_distance_atr"] = abs(float(touch_value) - entry_ema) / atr
            close_distance = close - entry_ema if side is Side.LONG else entry_ema - close
            result["ema_reclaim_strength_atr"] = close_distance / atr
            low_value = values.get("low")
            high_value = values.get("high")
            touched_ema = low_value is not None and float(low_value) <= entry_ema if side is Side.LONG else high_value is not None and float(high_value) >= entry_ema
            closed_back = close >= entry_ema if side is Side.LONG else close <= entry_ema
            result["ema_reclaim"] = 1.0 if touched_ema and closed_back else 0.0

        def side_aligned_return(lookback: int) -> float | None:
            if index < lookback:
                return None
            base_value = rows[index - lookback].values.get("close")
            if base_value is None:
                return None
            base = float(base_value)
            if base <= 0:
                return None
            raw = (close - base) / base
            return raw if side is Side.LONG else -raw

        for lookback in (3, 5):
            value = side_aligned_return(lookback)
            if value is not None:
                result[f"pre_entry_momentum_{lookback}_pct"] = value

        consecutive = 0
        for right_index in range(index, 0, -1):
            right = rows[right_index].values.get("close")
            left = rows[right_index - 1].values.get("close")
            if right is None or left is None:
                break
            moved_with_side = float(right) > float(left) if side is Side.LONG else float(right) < float(left)
            if not moved_with_side:
                break
            consecutive += 1
        result["pre_entry_consecutive_move"] = float(consecutive)

        if atr and atr > 0 and index >= 3:
            previous_fast = rows[index - 3].values.get(self.trend_fast_column)
            if previous_fast is not None and trend_fast is not None:
                raw_slope = (trend_fast - float(previous_fast)) / atr
                result["ema_fast_slope_3_atr"] = raw_slope if side is Side.LONG else -raw_slope

        prior_20 = previous[-20:]
        if prior_20:
            highs = [float(row.values["high"]) for row in prior_20 if row.values.get("high") is not None]
            lows = [float(row.values["low"]) for row in prior_20 if row.values.get("low") is not None]
            closes = [float(row.values["close"]) for row in prior_20 if row.values.get("close") is not None]
            if highs and lows:
                local_high = max(highs)
                local_low = min(lows)
                range_size = local_high - local_low
                if range_size > 0:
                    raw_position = (close - local_low) / range_size
                    result["local_range_position_20"] = raw_position if side is Side.LONG else 1 - raw_position
                    if atr and atr > 0:
                        extreme = local_high if side is Side.LONG else local_low
                        result["local_extreme_distance_atr"] = abs(close - extreme) / atr
            if len(closes) >= 2:
                net_move = abs(closes[-1] - closes[0])
                gross_move = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
                if gross_move > 0:
                    result["range_chop_score_20"] = max(0.0, min(1.0, 1.0 - net_move / gross_move))

        if atr and atr > 0:
            previous_high = base_features.get("previous_high")
            previous_low = base_features.get("previous_low")
            high_value = values.get("high")
            low_value = values.get("low")
            if side is Side.LONG and previous_high is not None and high_value is not None and float(high_value) > previous_high:
                result["breakout_wick_atr"] = max(0.0, float(high_value) - max(close, previous_high)) / atr
            elif side is Side.SHORT and previous_low is not None and low_value is not None and float(low_value) < previous_low:
                result["breakout_wick_atr"] = max(0.0, min(close, previous_low) - float(low_value)) / atr
            else:
                result["breakout_wick_atr"] = 0.0

        return result

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

    def _filters_allow_signal(self, *, rows, index: int, side: Side, feature_values: dict[str, float] | None = None) -> bool:
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
            elif filter_type == "pre_entry_momentum":
                if not _pre_entry_momentum_allows(rows=rows, index=index, filter_params=filter_params, side=side):
                    return False
            elif filter_type == "consecutive_move":
                if not _consecutive_move_allows(rows=rows, index=index, filter_params=filter_params, side=side):
                    return False
            elif filter_type == "local_range_position":
                if not _local_range_position_allows(rows=rows, index=index, filter_params=filter_params, side=side):
                    return False
            elif filter_type == "entry_context_exclusion":
                if feature_values is None:
                    return False
                if not _entry_context_exclusion_allows(feature_values=feature_values, filter_params=filter_params, side=side):
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


def _pre_entry_momentum_allows(*, rows, index: int, filter_params: dict[str, object], side: Side) -> bool:
    lookback_bars = int(filter_params.get("lookback_bars", 3))
    min_momentum_pct = _optional_float(filter_params.get("min_momentum_pct"))
    max_momentum_pct = _optional_float(filter_params.get("max_momentum_pct"))
    if lookback_bars <= 0:
        raise ValueError("pre_entry_momentum lookback_bars must be positive")
    if index < lookback_bars:
        return False
    current = rows[index].values.get("close")
    previous = rows[index - lookback_bars].values.get("close")
    if current is None or previous is None:
        return False
    previous_close = float(previous)
    if previous_close <= 0:
        return False
    raw = (float(current) - previous_close) / previous_close
    momentum_pct = raw if side is Side.LONG else -raw
    if min_momentum_pct is not None and momentum_pct < min_momentum_pct:
        return False
    if max_momentum_pct is not None and momentum_pct > max_momentum_pct:
        return False
    return True


def _consecutive_move_allows(*, rows, index: int, filter_params: dict[str, object], side: Side) -> bool:
    min_consecutive = int(filter_params.get("min_consecutive", 1))
    if min_consecutive <= 0:
        return True
    consecutive = 0
    for right_index in range(index, 0, -1):
        right = rows[right_index].values.get("close")
        left = rows[right_index - 1].values.get("close")
        if right is None or left is None:
            break
        moved_with_side = float(right) > float(left) if side is Side.LONG else float(right) < float(left)
        if not moved_with_side:
            break
        consecutive += 1
    return consecutive >= min_consecutive


def _local_range_position_allows(*, rows, index: int, filter_params: dict[str, object], side: Side) -> bool:
    lookback_bars = int(filter_params.get("lookback_bars", 20))
    min_position = _optional_float(filter_params.get("min_position"))
    max_position = _optional_float(filter_params.get("max_position"))
    if lookback_bars <= 1:
        raise ValueError("local_range_position lookback_bars must be greater than 1")
    start = max(0, index - lookback_bars)
    history = rows[start:index]
    if len(history) < max(3, min(lookback_bars, 10)):
        return False
    highs = [float(row.values["high"]) for row in history if row.values.get("high") is not None]
    lows = [float(row.values["low"]) for row in history if row.values.get("low") is not None]
    close_value = rows[index].values.get("close")
    if not highs or not lows or close_value is None:
        return False
    local_high = max(highs)
    local_low = min(lows)
    range_size = local_high - local_low
    if range_size <= 0:
        return False
    raw_position = (float(close_value) - local_low) / range_size
    position = raw_position if side is Side.LONG else 1 - raw_position
    if min_position is not None and position < min_position:
        return False
    if max_position is not None and position > max_position:
        return False
    return True


def _entry_context_exclusion_allows(*, feature_values: dict[str, float], filter_params: dict[str, object], side: Side) -> bool:
    side_param = filter_params.get("side")
    if side_param is not None and str(side_param) != side.value:
        return True
    conditions = filter_params.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("entry_context_exclusion conditions must be a non-empty list")
    for condition in conditions:
        if not isinstance(condition, dict):
            raise ValueError("entry_context_exclusion condition must be an object")
        field = str(condition.get("field") or "")
        if not field:
            raise ValueError("entry_context_exclusion condition.field must not be empty")
        value = feature_values.get(field)
        if value is None:
            return True
        numeric_value = float(value)
        min_value = _optional_float(condition.get("min"))
        max_value = _optional_float(condition.get("max"))
        if min_value is not None and numeric_value < min_value:
            return True
        if max_value is not None and numeric_value >= max_value:
            return True
    return False


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
