"""Trade-level attribution readmodels for research candidates."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path

from crypto_backtest_workbench.app.readmodels.research import (
    ParameterGroupView,
    build_parameter_research_workspace,
    build_research_workflow,
)
from crypto_backtest_workbench.app.readmodels.runs import load_run_detail_view
from crypto_backtest_workbench.domain.models import CanonicalCandle, MarketType, PriceType
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.engine.execution.simulator import simulate_signals
from crypto_backtest_workbench.engine.strategy import EMACrossoverStrategy, EMAPullbackATRStrategy, StrategyInput
from crypto_backtest_workbench.jobs.single_run import _filter_signals_for_segment
from crypto_backtest_workbench.storage.repositories import ResearchNoteRepository, RunRepository

MIN_TOTAL_TRADES = 30
MIN_OOS_TRADES = 10
MIN_RUN_COUNT = 2
MIN_BUCKET_TRADES = 8


@dataclass(slots=True, frozen=True)
class TradeAttributionBucket:
    dimension: str
    bucket_key: str
    label: str
    trade_count: int
    oos_trade_count: int
    win_rate: float
    net_pnl: float
    avg_return_pct: float
    profit_factor: float | None
    loss_contribution: float
    big_loss_count: int
    is_trade_count: int
    is_win_rate: float
    is_net_pnl: float
    is_avg_return_pct: float
    is_profit_factor: float | None
    is_loss_contribution: float
    is_big_loss_count: int
    oos_win_rate: float
    oos_net_pnl: float
    oos_avg_return_pct: float
    oos_profit_factor: float | None
    oos_loss_contribution: float
    oos_big_loss_count: int
    oos_confirms: bool | None
    is_underperforming: bool
    oos_underperforming: bool | None
    is_pf_delta: float | None
    oos_pf_delta: float | None
    is_avg_return_delta: float
    oos_avg_return_delta: float | None
    sample_ok: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class StopLossAttributionBucket:
    dimension: str
    bucket_key: str
    label: str
    is_trade_count: int
    is_stop_loss_count: int
    is_stop_loss_rate: float
    is_stop_loss_rate_delta: float
    is_stop_loss_net_pnl: float
    is_stop_loss_loss_share: float
    is_avg_loss_return_pct: float
    oos_trade_count: int
    oos_stop_loss_count: int
    oos_stop_loss_rate: float
    oos_stop_loss_rate_delta: float | None
    oos_stop_loss_net_pnl: float
    oos_stop_loss_loss_share: float
    oos_confirms: bool | None
    bucket_family: str
    sample_ok: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class EarlyFailAttributionBucket:
    dimension: str
    bucket_key: str
    label: str
    is_trade_count: int
    is_early_fail_count: int
    is_early_fail_rate: float
    is_early_fail_rate_delta: float
    is_first_bar_adverse_rate: float
    is_early_fail_stop_loss_rate: float
    oos_trade_count: int
    oos_early_fail_count: int
    oos_early_fail_rate: float
    oos_early_fail_rate_delta: float | None
    oos_first_bar_adverse_rate: float
    oos_early_fail_stop_loss_rate: float
    oos_confirms: bool | None
    bucket_family: str
    sample_ok: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TradeAttributionHypothesis:
    hypothesis_id: str
    description: str
    evidence: str
    risk_note: str
    status: str
    source_dimension: str
    source_bucket: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TradeAttributionView:
    candidate_id: str
    candidate: dict[str, object]
    summary: dict[str, object]
    anti_overfit_checks: tuple[dict[str, object], ...]
    buckets: tuple[TradeAttributionBucket, ...]
    early_fail_buckets: tuple[EarlyFailAttributionBucket, ...]
    stop_loss_buckets: tuple[StopLossAttributionBucket, ...]
    drawdown_trades: tuple[dict[str, object], ...]
    hypotheses: tuple[TradeAttributionHypothesis, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate": self.candidate,
            "summary": self.summary,
            "anti_overfit_checks": list(self.anti_overfit_checks),
            "buckets": [bucket.as_dict() for bucket in self.buckets],
            "early_fail_buckets": [bucket.as_dict() for bucket in self.early_fail_buckets],
            "stop_loss_buckets": [bucket.as_dict() for bucket in self.stop_loss_buckets],
            "drawdown_trades": list(self.drawdown_trades),
            "hypotheses": [hypothesis.as_dict() for hypothesis in self.hypotheses],
        }


def load_research_candidate_trade_attribution(
    run_repository: RunRepository,
    *,
    candidate_id: str,
    data_dir: Path | None = None,
) -> TradeAttributionView:
    groups = build_parameter_research_workspace(run_repository).parameter_groups
    group = next((item for item in groups if item.group_key == candidate_id), None)
    if group is None:
        raise FileNotFoundError(f"Research candidate not found: {candidate_id}")
    return build_trade_attribution_for_group(run_repository, group=group, data_dir=data_dir)


def build_stable_pool_trade_attribution(
    run_repository: RunRepository,
    note_repository: ResearchNoteRepository,
) -> dict[str, object]:
    groups_by_key = {
        group.group_key: group
        for group in build_parameter_research_workspace(run_repository).parameter_groups
    }
    workflow = build_research_workflow(run_repository, note_repository)
    stable_ids = [
        str(candidate.get("stable_candidate_id"))
        for candidate in workflow.stable_pool.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("stable_candidate_id")
    ]
    groups = [groups_by_key[group_id] for group_id in stable_ids if group_id in groups_by_key]
    return {
        "candidates": [
            build_trade_attribution_for_group(run_repository, group=group, data_dir=getattr(run_repository, "base_dir", None)).as_dict()
            for group in groups
        ],
    }


def build_trade_attribution_for_group(
    run_repository: RunRepository,
    *,
    group: ParameterGroupView,
    data_dir: Path | None = None,
) -> TradeAttributionView:
    trade_rows: list[dict[str, object]] = []
    for run_id in group.run_ids:
        try:
            detail = load_run_detail_view(run_repository, run_id)
        except FileNotFoundError:
            continue
        candles = _load_run_candles(detail=detail, data_dir=data_dir)
        for trade in detail.execution.trades:
            trade_rows.append(_trade_row(run_id=run_id, trade=trade, segment="is", candles=candles))
        trade_rows.extend(_load_oos_trade_rows(detail=detail, data_dir=data_dir))

    total_trades = len(trade_rows)
    oos_trades = sum(1 for row in trade_rows if row["segment"] == "oos")
    run_count = len({str(row["run_id"]) for row in trade_rows})
    total_net_pnl = sum(float(row["net_pnl"]) for row in trade_rows)
    is_rows = [row for row in trade_rows if row["segment"] == "is"]
    losses = [abs(float(row["net_pnl"])) for row in trade_rows if float(row["net_pnl"]) < 0]
    is_losses = [abs(float(row["net_pnl"])) for row in is_rows if float(row["net_pnl"]) < 0]
    total_loss_abs = sum(losses)
    total_is_loss_abs = sum(is_losses)
    total_oos_loss_abs = total_loss_abs - total_is_loss_abs
    is_baseline = _segment_baseline(is_rows)
    oos_baseline = _segment_baseline([row for row in trade_rows if row["segment"] == "oos"])
    big_loss_threshold = _percentile(losses, 0.8) if losses else None
    enriched_rows = [
        {
            **row,
            "labels": [
                *list(row["labels"]),
                *(
                    ["big_loss"]
                    if big_loss_threshold is not None and float(row["net_pnl"]) < 0 and abs(float(row["net_pnl"])) >= big_loss_threshold
                    else []
                ),
            ],
        }
        for row in trade_rows
    ]
    checks = _anti_overfit_checks(
        total_trades=total_trades,
        oos_trades=oos_trades,
        run_count=run_count,
        feature_meta_coverage=_feature_meta_coverage(enriched_rows),
    )
    buckets = _build_buckets(
        enriched_rows,
        total_loss_abs=total_loss_abs,
        total_is_loss_abs=total_is_loss_abs,
        total_oos_loss_abs=total_oos_loss_abs,
        is_baseline=is_baseline,
        oos_baseline=oos_baseline,
    )
    early_fail_buckets = _build_early_fail_buckets(enriched_rows)
    stop_loss_buckets = _build_stop_loss_buckets(enriched_rows)
    hypotheses = _build_hypotheses(buckets, checks_passed=all(bool(check["passed"]) for check in checks))
    early_path_is_rows = [row for row in enriched_rows if row["segment"] == "is" and _has_early_path(row)]
    early_path_oos_rows = [row for row in enriched_rows if row["segment"] == "oos" and _has_early_path(row)]
    summary = {
        "run_count": run_count,
        "trade_count": total_trades,
        "oos_trade_count": oos_trades,
        "win_rate": _win_rate(enriched_rows),
        "net_pnl": total_net_pnl,
        "profit_factor": _profit_factor(enriched_rows),
        "feature_meta_coverage": _feature_meta_coverage(enriched_rows),
        "early_path_is_trade_count": len(early_path_is_rows),
        "early_path_oos_trade_count": len(early_path_oos_rows),
        "is_early_fail_rate": _early_fail_rate(early_path_is_rows),
        "oos_early_fail_rate": _early_fail_rate(early_path_oos_rows),
        "hypothesis_count": len(hypotheses),
        "anti_overfit_passed": all(bool(check["passed"]) for check in checks),
    }
    return TradeAttributionView(
        candidate_id=group.group_key,
        candidate={
            "strategy_name": group.strategy_name,
            "symbol": group.symbol,
            "timeframe": group.timeframe,
            "parameter_summary": group.parameter_summary,
            "signal_filter_summary": group.signal_filter_summary,
            "run_ids": list(group.run_ids),
        },
        summary=summary,
        anti_overfit_checks=tuple(checks),
        buckets=tuple(buckets),
        early_fail_buckets=tuple(early_fail_buckets),
        stop_loss_buckets=tuple(stop_loss_buckets),
        drawdown_trades=tuple(_drawdown_trades(enriched_rows)),
        hypotheses=tuple(hypotheses),
    )


def _segment_start(validation_summary: dict[str, object] | None, segment_name: str) -> datetime | None:
    if not validation_summary:
        return None
    segment = validation_summary.get(segment_name)
    if not isinstance(segment, dict):
        return None
    value = segment.get("analysis_start")
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _segment_window(validation_summary: dict[str, object] | None, segment_name: str) -> tuple[datetime, datetime] | None:
    if not validation_summary:
        return None
    segment = validation_summary.get(segment_name)
    if not isinstance(segment, dict):
        return None
    start = segment.get("analysis_start")
    end = segment.get("analysis_end")
    if not start or not end:
        return None
    return datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))


def _trade_row(*, run_id: str, trade, segment: str, candles: list[CanonicalCandle] | None = None) -> dict[str, object]:
    return {
        "run_id": run_id,
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "side": trade.side.value,
        "entry_time": trade.entry_time.isoformat(),
        "exit_time": trade.exit_time.isoformat() if trade.exit_time is not None else None,
        "exit_reason": trade.exit_reason or "open",
        "net_pnl": trade.net_pnl,
        "return_pct": trade.return_pct,
        "holding_bars": trade.holding_bars,
        "segment": segment,
        "labels": _trade_labels(trade.net_pnl),
        "features": _trade_features(trade, candles=candles),
    }


def _load_oos_trade_rows(*, detail, data_dir: Path | None) -> list[dict[str, object]]:
    if data_dir is None or detail.validation_summary is None:
        return []
    window = _segment_window(detail.validation_summary, "oos_segment")
    if window is None:
        return []
    try:
        candles = _load_dataset_candles(data_dir=data_dir, snapshot_id=detail.run.dataset_snapshot_id)
        oos_candles = [candle for candle in candles if window[0] <= candle.timestamp <= window[1]]
        if not oos_candles:
            return []
        signals = _generate_run_signals(detail=detail, data_dir=data_dir)
        oos_signals = _filter_signals_for_segment(signals, oos_candles)
        execution = simulate_signals(
            candles=oos_candles,
            signals=oos_signals,
            constraints=_execution_constraints(detail.manifest.resolved_config_json),
        )
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        return []
    return [_trade_row(run_id=detail.run.run_id, trade=trade, segment="oos", candles=oos_candles) for trade in execution.trades]


def _load_run_candles(*, detail, data_dir: Path | None) -> list[CanonicalCandle] | None:
    if data_dir is None:
        return None
    try:
        return _load_dataset_candles(data_dir=data_dir, snapshot_id=detail.run.dataset_snapshot_id)
    except FileNotFoundError:
        return None


def _generate_run_signals(*, detail, data_dir: Path):
    resolved_config = detail.manifest.resolved_config_json
    strategy_params = dict(resolved_config.get("strategy_params") or {})
    strategy_name = str(resolved_config.get("strategy_name") or detail.run.strategy_name)
    strategy_params.setdefault("strategy_name", strategy_name)
    strategy = _build_strategy(strategy_params)
    feature_artifact_id = str(resolved_config.get("feature_artifact_id") or detail.manifest.feature_artifact_id)
    feature_uri = str(data_dir / "features" / feature_artifact_id / "feature_rows.csv")
    return strategy.generate_signals(
        StrategyInput(
            run_id=detail.run.run_id,
            symbol=str(resolved_config.get("symbol") or ""),
            timeframe=str(resolved_config.get("timeframe") or ""),
            feature_artifact_id=feature_artifact_id,
            features_uri=feature_uri,
            config={"qty_policy_ref": getattr(strategy, "qty_policy_ref", "fixed_notional_v1")},
        )
    )


def _build_strategy(strategy_params: dict[str, object]):
    strategy_name = str(strategy_params.get("strategy_name") or strategy_params.get("name") or "ema_crossover")
    payload = {key: value for key, value in strategy_params.items() if key not in {"strategy_name", "name", "version"}}
    if strategy_name == "ema_pullback_atr_v2":
        return EMAPullbackATRStrategy(**payload)
    if strategy_name == "ema_crossover":
        return EMACrossoverStrategy(**payload)
    raise ValueError(f"Unsupported strategy_name: {strategy_name}")


def _execution_constraints(resolved_config: dict[str, object]) -> ExecutionConstraints:
    payload = resolved_config.get("execution_constraints")
    if not isinstance(payload, dict):
        return ExecutionConstraints()
    return ExecutionConstraints(
        initial_cash=float(payload.get("initial_cash", 10_000.0)),
        leverage=float(payload.get("leverage", 1.0)),
        fee_rate=float(payload.get("fee_rate", 0.0)),
        slippage_bps=float(payload.get("slippage_bps", 0.0)),
        min_notional=float(payload.get("min_notional", 0.0)),
        qty_by_policy={str(key): float(value) for key, value in dict(payload.get("qty_by_policy") or {}).items()},
        cash_allocation_pct_by_policy={
            str(key): float(value) for key, value in dict(payload.get("cash_allocation_pct_by_policy") or {}).items()
        },
        risk_pct_per_trade_by_policy={
            str(key): float(value) for key, value in dict(payload.get("risk_pct_per_trade_by_policy") or {}).items()
        },
    )


def _load_dataset_candles(*, data_dir: Path, snapshot_id: str) -> list[CanonicalCandle]:
    path = data_dir / "datasets" / snapshot_id / "canonical_candles.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            CanonicalCandle(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                symbol=row["symbol"],
                exchange=row["exchange"],
                market_type=MarketType(row["market_type"]),
                timeframe=row["timeframe"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                price_type=PriceType(row.get("price_type", PriceType.LAST.value)),
                data_source=row.get("data_source", "unknown"),
            )
            for row in reader
        ]


def _trade_features(trade, *, candles: list[CanonicalCandle] | None = None) -> dict[str, float]:
    features: dict[str, float] = {}
    stop = _finite_float(trade.planned_stop_loss_price)
    take_profit = _finite_float(trade.planned_take_profit_price)
    entry = _finite_float(trade.entry_price)
    if entry and stop:
        stop_distance = abs(entry - stop)
        features["stop_distance_pct"] = stop_distance / entry
    if entry and take_profit:
        take_profit_distance = abs(take_profit - entry)
        features["take_profit_distance_pct"] = take_profit_distance / entry
    if "stop_distance_pct" in features and "take_profit_distance_pct" in features and features["stop_distance_pct"] > 0:
        features["reward_risk_ratio"] = features["take_profit_distance_pct"] / features["stop_distance_pct"]
    features["holding_bars"] = float(trade.holding_bars)

    meta = getattr(trade, "entry_signal_meta_json", {}) or {}
    raw_features = meta.get("feature_values") if isinstance(meta, dict) else None
    if isinstance(raw_features, dict):
        for key in ("trend_fast_ema", "trend_slow_ema", "entry_ema", "atr", "close", "high", "low", "previous_high", "previous_low"):
            value = _finite_float(raw_features.get(key))
            if value is not None:
                features[key] = value
        close = features.get("close")
        atr = features.get("atr")
        if close and atr:
            features["atr_pct"] = atr / close
        trend_fast = features.get("trend_fast_ema")
        trend_slow = features.get("trend_slow_ema")
        if close and trend_fast is not None and trend_slow is not None:
            features["trend_gap_pct"] = abs(trend_fast - trend_slow) / close
        if atr and trend_fast is not None and trend_slow is not None:
            features["trend_gap_atr"] = abs(trend_fast - trend_slow) / atr
        entry_ema = features.get("entry_ema")
        low = features.get("low")
        high = features.get("high")
        if atr and entry_ema is not None:
            touch_price = low if trade.side.value == "long" else high
            if touch_price is not None:
                features["entry_distance_atr"] = abs(touch_price - entry_ema) / atr
        previous_high = features.get("previous_high")
        previous_low = features.get("previous_low")
        if atr and close is not None:
            breakout_ref = previous_high if trade.side.value == "long" else previous_low
            if breakout_ref is not None:
                features["breakout_distance_atr"] = abs(close - breakout_ref) / atr
    if candles:
        features.update(_trade_entry_context_features(trade, candles, features))
        features.update(_trade_path_features(trade, candles, features))
    return features


def _trade_entry_context_features(trade, candles: list[CanonicalCandle], features: dict[str, float]) -> dict[str, float]:
    entry = _finite_float(trade.entry_price)
    if not entry or entry <= 0:
        return {}
    history = [candle for candle in candles if candle.timestamp <= trade.entry_time]
    if not history:
        return {}
    current = history[-1]
    previous = history[:-1]
    side = trade.side.value
    result: dict[str, float] = {}

    def side_aligned_return(lookback: int) -> float | None:
        if len(history) <= lookback:
            return None
        base = history[-lookback - 1].close
        if base <= 0:
            return None
        raw = (current.close - base) / base
        return raw if side == "long" else -raw

    for lookback in (3, 5):
        value = side_aligned_return(lookback)
        if value is not None:
            result[f"pre_entry_momentum_{lookback}_pct"] = value

    consecutive = 0
    for left, right in zip(reversed(history[:-1]), reversed(history)):
        moved_with_side = right.close > left.close if side == "long" else right.close < left.close
        if not moved_with_side:
            break
        consecutive += 1
    result["pre_entry_consecutive_move"] = float(consecutive)

    atr = features.get("atr")
    entry_ema = features.get("entry_ema")
    if atr and atr > 0 and entry_ema is not None:
        close_distance = current.close - entry_ema if side == "long" else entry_ema - current.close
        result["ema_reclaim_strength_atr"] = close_distance / atr
        touched_ema = current.low <= entry_ema if side == "long" else current.high >= entry_ema
        closed_back = current.close >= entry_ema if side == "long" else current.close <= entry_ema
        result["ema_reclaim"] = 1.0 if touched_ema and closed_back else 0.0

    prior_20 = previous[-20:]
    if prior_20:
        local_high = max(candle.high for candle in prior_20)
        local_low = min(candle.low for candle in prior_20)
        range_size = local_high - local_low
        if range_size > 0:
            raw_position = (current.close - local_low) / range_size
            result["local_range_position_20"] = raw_position if side == "long" else 1 - raw_position
        if atr and atr > 0:
            extreme = local_high if side == "long" else local_low
            result["local_extreme_distance_atr"] = abs(current.close - extreme) / atr

    previous_high = features.get("previous_high")
    previous_low = features.get("previous_low")
    if atr and atr > 0:
        if side == "long" and previous_high is not None and current.high > previous_high:
            result["breakout_wick_atr"] = max(0.0, current.high - max(current.close, previous_high)) / atr
        elif side == "short" and previous_low is not None and current.low < previous_low:
            result["breakout_wick_atr"] = max(0.0, min(current.close, previous_low) - current.low) / atr
        else:
            result["breakout_wick_atr"] = 0.0

    volatility_window = previous[-100:]
    atr_pct = features.get("atr_pct")
    if atr_pct is not None and volatility_window:
        ranges = [
            (candle.high - candle.low) / candle.close
            for candle in volatility_window
            if candle.close > 0 and candle.high >= candle.low
        ]
        if ranges:
            below_or_equal = sum(1 for item in ranges if item <= atr_pct)
            result["volatility_percentile_100"] = below_or_equal / len(ranges)

    return result


def _trade_path_features(trade, candles: list[CanonicalCandle], features: dict[str, float]) -> dict[str, float]:
    entry = _finite_float(trade.entry_price)
    if not entry or entry <= 0:
        return {}
    exit_time = trade.exit_time or trade.entry_time
    path = [candle for candle in candles if trade.entry_time <= candle.timestamp <= exit_time]
    if not path:
        path = [candle for candle in candles if candle.timestamp >= trade.entry_time][: max(1, min(3, trade.holding_bars or 3))]
    if not path:
        return {}
    first_bar = path[:1]
    first_three = path[:3]

    def favorable_adverse(items: list[CanonicalCandle]) -> tuple[float, float]:
        if not items:
            return 0.0, 0.0
        if trade.side.value == "long":
            favorable = max(candle.high for candle in items) - entry
            adverse = entry - min(candle.low for candle in items)
        else:
            favorable = entry - min(candle.low for candle in items)
            adverse = max(candle.high for candle in items) - entry
        return max(0.0, favorable) / entry, max(0.0, adverse) / entry

    favorable_1, adverse_1 = favorable_adverse(first_bar)
    favorable_3, adverse_3 = favorable_adverse(first_three)
    stop_distance = features.get("stop_distance_pct") or 0.0
    result = {
        "path_mfe_1_pct": favorable_1,
        "path_mae_1_pct": adverse_1,
        "path_mfe_3_pct": favorable_3,
        "path_mae_3_pct": adverse_3,
        "path_first_bar_adverse": 1.0 if adverse_1 > favorable_1 else 0.0,
    }
    if stop_distance > 0:
        result["path_mfe_3_stop_r"] = favorable_3 / stop_distance
        result["path_mae_1_stop_r"] = adverse_1 / stop_distance
        result["path_mae_3_stop_r"] = adverse_3 / stop_distance
        result["path_no_favorable_3"] = 1.0 if favorable_3 < stop_distance * 0.25 else 0.0
    return result


def _trade_labels(net_pnl: float) -> list[str]:
    if net_pnl > 0:
        return ["winner"]
    if net_pnl < 0:
        return ["loser"]
    return ["flat"]


def _build_buckets(
    rows: list[dict[str, object]],
    *,
    total_loss_abs: float,
    total_is_loss_abs: float,
    total_oos_loss_abs: float,
    is_baseline: dict[str, float | None],
    oos_baseline: dict[str, float | None],
) -> list[TradeAttributionBucket]:
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        _append_bucket(bucket_rows, "side", str(row["side"]), str(row["side"]), row)
        _append_bucket(bucket_rows, "exit_reason", str(row["exit_reason"]), str(row["exit_reason"]), row)
        _append_bucket(bucket_rows, "segment", str(row["segment"]), "OOS" if row["segment"] == "oos" else "IS", row)
        features = row.get("features")
        if isinstance(features, dict):
            for feature_name in (
                "stop_distance_pct",
                "take_profit_distance_pct",
                "reward_risk_ratio",
                "holding_bars",
                "atr_pct",
                "trend_gap_pct",
                "trend_gap_atr",
                "entry_distance_atr",
                "breakout_distance_atr",
                "pre_entry_momentum_3_pct",
                "pre_entry_momentum_5_pct",
                "pre_entry_consecutive_move",
                "local_range_position_20",
                "local_extreme_distance_atr",
                "ema_reclaim",
                "ema_reclaim_strength_atr",
                "breakout_wick_atr",
                "volatility_percentile_100",
            ):
                value = _finite_float(features.get(feature_name))
                if value is None:
                    continue
                bucket_key, label = _feature_bucket(feature_name, value)
                _append_bucket(bucket_rows, feature_name, bucket_key, label, row)

    buckets = [
        _summarize_bucket(
            dimension,
            bucket_key,
            label,
            entries,
            total_loss_abs=total_loss_abs,
            total_is_loss_abs=total_is_loss_abs,
            total_oos_loss_abs=total_oos_loss_abs,
            is_baseline=is_baseline,
            oos_baseline=oos_baseline,
        )
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]
    return sorted(
        buckets,
        key=lambda item: (
            item.is_underperforming,
            item.oos_confirms is True,
            abs(item.is_avg_return_delta),
            item.is_loss_contribution,
            item.is_trade_count,
        ),
        reverse=True,
    )


def _append_bucket(
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]],
    dimension: str,
    bucket_key: str,
    label: str,
    row: dict[str, object],
) -> None:
    bucket_rows.setdefault((dimension, bucket_key, label), []).append(row)


def _build_early_fail_buckets(rows: list[dict[str, object]]) -> list[EarlyFailAttributionBucket]:
    is_rows = [row for row in rows if row["segment"] == "is" and _has_early_path(row)]
    oos_rows = [row for row in rows if row["segment"] == "oos" and _has_early_path(row)]
    is_baseline = _early_fail_rate(is_rows)
    oos_baseline = _early_fail_rate(oos_rows)
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        if not _has_early_path(row):
            continue
        _append_bucket(bucket_rows, "side", str(row["side"]), str(row["side"]), row)
        features = row.get("features")
        if not isinstance(features, dict):
            continue
        for feature_name in (
            "stop_distance_pct",
            "take_profit_distance_pct",
            "reward_risk_ratio",
            "atr_pct",
            "trend_gap_pct",
            "trend_gap_atr",
            "entry_distance_atr",
            "breakout_distance_atr",
            "pre_entry_momentum_3_pct",
            "pre_entry_momentum_5_pct",
            "pre_entry_consecutive_move",
            "local_range_position_20",
            "local_extreme_distance_atr",
            "ema_reclaim",
            "ema_reclaim_strength_atr",
            "breakout_wick_atr",
            "volatility_percentile_100",
        ):
            value = _finite_float(features.get(feature_name))
            if value is None:
                continue
            bucket_key, label = _feature_bucket(feature_name, value)
            _append_bucket(bucket_rows, feature_name, bucket_key, label, row)
    buckets = [
        _summarize_early_fail_bucket(
            dimension,
            bucket_key,
            label,
            entries,
            is_baseline=is_baseline,
            oos_baseline=oos_baseline,
        )
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]
    buckets.extend(_build_early_fail_combo_buckets(rows, is_baseline=is_baseline, oos_baseline=oos_baseline))
    return sorted(
        buckets,
        key=lambda item: (
            item.sample_ok,
            item.oos_confirms is True,
            item.bucket_family == "combo",
            item.is_early_fail_rate_delta,
            item.is_early_fail_count,
        ),
        reverse=True,
    )


def _summarize_early_fail_bucket(
    dimension: str,
    bucket_key: str,
    label: str,
    rows: list[dict[str, object]],
    *,
    is_baseline: float,
    oos_baseline: float,
    bucket_family: str = "single",
) -> EarlyFailAttributionBucket:
    is_rows = [row for row in rows if row["segment"] == "is" and _has_early_path(row)]
    oos_rows = [row for row in rows if row["segment"] == "oos" and _has_early_path(row)]
    is_rate = _early_fail_rate(is_rows)
    oos_rate = _early_fail_rate(oos_rows)
    is_delta = is_rate - is_baseline
    oos_delta = oos_rate - oos_baseline if oos_rows else None
    oos_confirms = None
    if len(oos_rows) >= MIN_OOS_TRADES and is_delta >= 0.05:
        oos_confirms = bool(oos_delta is not None and oos_delta >= 0.03)
    return EarlyFailAttributionBucket(
        dimension=dimension,
        bucket_key=bucket_key,
        label=label,
        is_trade_count=len(is_rows),
        is_early_fail_count=len(_early_fail_rows(is_rows)),
        is_early_fail_rate=is_rate,
        is_early_fail_rate_delta=is_delta,
        is_first_bar_adverse_rate=_first_bar_adverse_rate(is_rows),
        is_early_fail_stop_loss_rate=_stop_loss_rate(_early_fail_rows(is_rows)),
        oos_trade_count=len(oos_rows),
        oos_early_fail_count=len(_early_fail_rows(oos_rows)),
        oos_early_fail_rate=oos_rate,
        oos_early_fail_rate_delta=oos_delta,
        oos_first_bar_adverse_rate=_first_bar_adverse_rate(oos_rows),
        oos_early_fail_stop_loss_rate=_stop_loss_rate(_early_fail_rows(oos_rows)),
        oos_confirms=oos_confirms,
        bucket_family=bucket_family,
        sample_ok=len(is_rows) >= MIN_BUCKET_TRADES,
    )


def _build_early_fail_combo_buckets(
    rows: list[dict[str, object]],
    *,
    is_baseline: float,
    oos_baseline: float,
) -> list[EarlyFailAttributionBucket]:
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    combos = [
        ("趋势+回踩", ("trend_gap_atr", "entry_distance_atr")),
        ("趋势+突破", ("trend_gap_atr", "breakout_distance_atr")),
        ("波动+回踩", ("atr_pct", "entry_distance_atr")),
        ("方向+趋势", ("side", "trend_gap_atr")),
        ("动量+回踩", ("pre_entry_momentum_3_pct", "entry_distance_atr")),
        ("局部位置+突破", ("local_range_position_20", "breakout_wick_atr")),
        ("波动分位+趋势", ("volatility_percentile_100", "trend_gap_atr")),
        ("EMA收回+突破", ("ema_reclaim", "breakout_wick_atr")),
    ]
    for row in rows:
        if not _has_early_path(row):
            continue
        features = row.get("features")
        if not isinstance(features, dict):
            continue
        for combo_name, keys in combos:
            parts: list[str] = []
            labels: list[str] = []
            missing = False
            for key in keys:
                if key == "side":
                    parts.append(str(row["side"]))
                    labels.append(str(row["side"]))
                    continue
                value = _finite_float(features.get(key))
                if value is None:
                    missing = True
                    break
                bucket_key, label = _feature_bucket(key, value)
                parts.append(bucket_key)
                labels.append(label.replace(f"{key} ", ""))
            if missing:
                continue
            _append_bucket(bucket_rows, combo_name, "|".join(parts), " + ".join(labels), row)
    return [
        _summarize_early_fail_bucket(
            dimension,
            bucket_key,
            label,
            entries,
            is_baseline=is_baseline,
            oos_baseline=oos_baseline,
            bucket_family="combo",
        )
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]


def _has_early_path(row: dict[str, object]) -> bool:
    features = row.get("features")
    return isinstance(features, dict) and _finite_float(features.get("path_no_favorable_3")) is not None


def _early_fail_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        features = row.get("features")
        if isinstance(features, dict) and _finite_float(features.get("path_no_favorable_3")) == 1.0:
            result.append(row)
    return result


def _early_fail_rate(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    return len(_early_fail_rows(rows)) / len(rows)


def _first_bar_adverse_rate(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    count = 0
    for row in rows:
        features = row.get("features")
        if isinstance(features, dict) and _finite_float(features.get("path_first_bar_adverse")) == 1.0:
            count += 1
    return count / len(rows)


def _build_stop_loss_buckets(rows: list[dict[str, object]]) -> list[StopLossAttributionBucket]:
    is_rows = [row for row in rows if row["segment"] == "is"]
    oos_rows = [row for row in rows if row["segment"] == "oos"]
    is_baseline = _stop_loss_rate(is_rows)
    oos_baseline = _stop_loss_rate(oos_rows)
    total_is_stop_loss_abs = _stop_loss_abs(is_rows)
    total_oos_stop_loss_abs = _stop_loss_abs(oos_rows)
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        _append_bucket(bucket_rows, "side", str(row["side"]), str(row["side"]), row)
        features = row.get("features")
        if not isinstance(features, dict):
            continue
        for feature_name in (
            "stop_distance_pct",
            "take_profit_distance_pct",
            "reward_risk_ratio",
            "atr_pct",
            "trend_gap_pct",
            "trend_gap_atr",
            "entry_distance_atr",
            "breakout_distance_atr",
            "pre_entry_momentum_3_pct",
            "pre_entry_momentum_5_pct",
            "pre_entry_consecutive_move",
            "local_range_position_20",
            "local_extreme_distance_atr",
            "ema_reclaim",
            "ema_reclaim_strength_atr",
            "breakout_wick_atr",
            "volatility_percentile_100",
            "path_mfe_3_stop_r",
            "path_mae_1_stop_r",
            "path_mae_3_stop_r",
            "path_first_bar_adverse",
            "path_no_favorable_3",
        ):
            value = _finite_float(features.get(feature_name))
            if value is None:
                continue
            bucket_key, label = _feature_bucket(feature_name, value)
            _append_bucket(bucket_rows, feature_name, bucket_key, label, row)

    buckets = [
        _summarize_stop_loss_bucket(
            dimension,
            bucket_key,
            label,
            entries,
            is_baseline=is_baseline,
            oos_baseline=oos_baseline,
            total_is_stop_loss_abs=total_is_stop_loss_abs,
            total_oos_stop_loss_abs=total_oos_stop_loss_abs,
        )
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]
    buckets.extend(_build_stop_loss_combo_buckets(rows, is_baseline=is_baseline, oos_baseline=oos_baseline, total_is_stop_loss_abs=total_is_stop_loss_abs, total_oos_stop_loss_abs=total_oos_stop_loss_abs))
    return sorted(
        buckets,
        key=lambda item: (
            item.sample_ok,
            item.oos_confirms is True,
            item.is_stop_loss_loss_share,
            item.is_stop_loss_rate_delta,
            item.is_stop_loss_count,
        ),
        reverse=True,
    )


def _build_stop_loss_combo_buckets(
    rows: list[dict[str, object]],
    *,
    is_baseline: float,
    oos_baseline: float,
    total_is_stop_loss_abs: float,
    total_oos_stop_loss_abs: float,
) -> list[StopLossAttributionBucket]:
    bucket_rows: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        features = row.get("features")
        if not isinstance(features, dict):
            continue
        combos = [
            ("方向+早期路径", ("side", "path_first_bar_adverse", "path_no_favorable_3")),
            ("趋势+早期路径", ("trend_gap_atr", "path_first_bar_adverse", "path_no_favorable_3")),
            ("贴近度+早期路径", ("entry_distance_atr", "path_first_bar_adverse", "path_no_favorable_3")),
            ("止损距离+早期路径", ("stop_distance_pct", "path_first_bar_adverse", "path_no_favorable_3")),
        ]
        for combo_name, keys in combos:
            parts: list[str] = []
            labels: list[str] = []
            missing = False
            for key in keys:
                if key == "side":
                    parts.append(str(row["side"]))
                    labels.append(str(row["side"]))
                    continue
                value = _finite_float(features.get(key))
                if value is None:
                    missing = True
                    break
                bucket_key, label = _feature_bucket(key, value)
                parts.append(bucket_key)
                labels.append(label.replace(f"{key} ", ""))
            if missing:
                continue
            _append_bucket(
                bucket_rows,
                combo_name,
                "|".join(parts),
                " + ".join(labels),
                row,
            )
    return [
        _summarize_stop_loss_bucket(
            dimension,
            bucket_key,
            label,
            entries,
            is_baseline=is_baseline,
            oos_baseline=oos_baseline,
            total_is_stop_loss_abs=total_is_stop_loss_abs,
            total_oos_stop_loss_abs=total_oos_stop_loss_abs,
            bucket_family="combo",
        )
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]


def _summarize_stop_loss_bucket(
    dimension: str,
    bucket_key: str,
    label: str,
    rows: list[dict[str, object]],
    *,
    is_baseline: float,
    oos_baseline: float,
    total_is_stop_loss_abs: float,
    total_oos_stop_loss_abs: float,
    bucket_family: str = "single",
) -> StopLossAttributionBucket:
    is_rows = [row for row in rows if row["segment"] == "is"]
    oos_rows = [row for row in rows if row["segment"] == "oos"]
    is_rate = _stop_loss_rate(is_rows)
    oos_rate = _stop_loss_rate(oos_rows)
    is_delta = is_rate - is_baseline
    oos_delta = oos_rate - oos_baseline if oos_rows else None
    oos_confirms = None
    if len(oos_rows) >= MIN_OOS_TRADES and is_delta >= 0.05:
        oos_confirms = bool(oos_delta is not None and oos_delta >= 0.03)
    is_stop_loss_rows = _stop_loss_rows(is_rows)
    oos_stop_loss_rows = _stop_loss_rows(oos_rows)
    is_stop_loss_net_pnl = sum(float(row["net_pnl"]) for row in is_stop_loss_rows)
    oos_stop_loss_net_pnl = sum(float(row["net_pnl"]) for row in oos_stop_loss_rows)
    return StopLossAttributionBucket(
        dimension=dimension,
        bucket_key=bucket_key,
        label=label,
        is_trade_count=len(is_rows),
        is_stop_loss_count=len(is_stop_loss_rows),
        is_stop_loss_rate=is_rate,
        is_stop_loss_rate_delta=is_delta,
        is_stop_loss_net_pnl=is_stop_loss_net_pnl,
        is_stop_loss_loss_share=abs(is_stop_loss_net_pnl) / total_is_stop_loss_abs if total_is_stop_loss_abs > 0 else 0.0,
        is_avg_loss_return_pct=(
            sum(float(row["return_pct"]) for row in is_stop_loss_rows) / len(is_stop_loss_rows)
            if is_stop_loss_rows
            else 0.0
        ),
        oos_trade_count=len(oos_rows),
        oos_stop_loss_count=len(oos_stop_loss_rows),
        oos_stop_loss_rate=oos_rate,
        oos_stop_loss_rate_delta=oos_delta,
        oos_stop_loss_net_pnl=oos_stop_loss_net_pnl,
        oos_stop_loss_loss_share=abs(oos_stop_loss_net_pnl) / total_oos_stop_loss_abs if total_oos_stop_loss_abs > 0 else 0.0,
        oos_confirms=oos_confirms,
        bucket_family=bucket_family,
        sample_ok=len(is_rows) >= MIN_BUCKET_TRADES,
    )


def _stop_loss_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if str(row["exit_reason"]) == "stop_loss_intrabar"]


def _stop_loss_rate(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    return len(_stop_loss_rows(rows)) / len(rows)


def _stop_loss_abs(rows: list[dict[str, object]]) -> float:
    return abs(sum(float(row["net_pnl"]) for row in _stop_loss_rows(rows)))


def _summarize_bucket(
    dimension: str,
    bucket_key: str,
    label: str,
    rows: list[dict[str, object]],
    *,
    total_loss_abs: float,
    total_is_loss_abs: float,
    total_oos_loss_abs: float,
    is_baseline: dict[str, float | None],
    oos_baseline: dict[str, float | None],
) -> TradeAttributionBucket:
    is_rows = [row for row in rows if row["segment"] == "is"]
    oos_rows = [row for row in rows if row["segment"] == "oos"]
    losses = [abs(float(row["net_pnl"])) for row in rows if float(row["net_pnl"]) < 0]
    is_losses = [abs(float(row["net_pnl"])) for row in is_rows if float(row["net_pnl"]) < 0]
    oos_losses = [abs(float(row["net_pnl"])) for row in oos_rows if float(row["net_pnl"]) < 0]
    loss_abs = sum(losses)
    is_loss_abs = sum(is_losses)
    oos_loss_abs = sum(oos_losses)
    is_net_pnl = sum(float(row["net_pnl"]) for row in is_rows)
    oos_net_pnl = sum(float(row["net_pnl"]) for row in oos_rows)
    is_profit_factor = _profit_factor(is_rows)
    oos_profit_factor = _profit_factor(oos_rows)
    is_avg_return_pct = sum(float(row["return_pct"]) for row in is_rows) / len(is_rows) if is_rows else 0.0
    oos_avg_return_pct = sum(float(row["return_pct"]) for row in oos_rows) / len(oos_rows) if oos_rows else 0.0
    is_pf_delta = _metric_delta(is_profit_factor, is_baseline.get("profit_factor"))
    oos_pf_delta = _metric_delta(oos_profit_factor, oos_baseline.get("profit_factor"))
    is_avg_return_delta = is_avg_return_pct - float(is_baseline.get("avg_return_pct") or 0.0)
    oos_avg_return_delta = (
        oos_avg_return_pct - float(oos_baseline.get("avg_return_pct") or 0.0)
        if oos_rows
        else None
    )
    is_underperforming = _is_underperforming(
        trade_count=len(is_rows),
        net_pnl=is_net_pnl,
        profit_factor=is_profit_factor,
        profit_factor_delta=is_pf_delta,
        avg_return_delta=is_avg_return_delta,
    )
    oos_underperforming = (
        _is_underperforming(
            trade_count=len(oos_rows),
            net_pnl=oos_net_pnl,
            profit_factor=oos_profit_factor,
            profit_factor_delta=oos_pf_delta,
            avg_return_delta=oos_avg_return_delta or 0.0,
        )
        if len(oos_rows) >= MIN_OOS_TRADES
        else None
    )
    return TradeAttributionBucket(
        dimension=dimension,
        bucket_key=bucket_key,
        label=label,
        trade_count=len(rows),
        oos_trade_count=len(oos_rows),
        win_rate=_win_rate(rows),
        net_pnl=sum(float(row["net_pnl"]) for row in rows),
        avg_return_pct=sum(float(row["return_pct"]) for row in rows) / len(rows) if rows else 0.0,
        profit_factor=_profit_factor(rows),
        loss_contribution=loss_abs / total_loss_abs if total_loss_abs > 0 else 0.0,
        big_loss_count=sum(1 for row in rows if "big_loss" in row.get("labels", [])),
        is_trade_count=len(is_rows),
        is_win_rate=_win_rate(is_rows),
        is_net_pnl=is_net_pnl,
        is_avg_return_pct=is_avg_return_pct,
        is_profit_factor=is_profit_factor,
        is_loss_contribution=is_loss_abs / total_is_loss_abs if total_is_loss_abs > 0 else 0.0,
        is_big_loss_count=sum(1 for row in is_rows if "big_loss" in row.get("labels", [])),
        oos_win_rate=_win_rate(oos_rows),
        oos_net_pnl=oos_net_pnl,
        oos_avg_return_pct=oos_avg_return_pct,
        oos_profit_factor=oos_profit_factor,
        oos_loss_contribution=oos_loss_abs / total_oos_loss_abs if total_oos_loss_abs > 0 else 0.0,
        oos_big_loss_count=sum(1 for row in oos_rows if "big_loss" in row.get("labels", [])),
        oos_confirms=oos_underperforming if is_underperforming else None,
        is_underperforming=is_underperforming,
        oos_underperforming=oos_underperforming,
        is_pf_delta=is_pf_delta,
        oos_pf_delta=oos_pf_delta,
        is_avg_return_delta=is_avg_return_delta,
        oos_avg_return_delta=oos_avg_return_delta,
        sample_ok=len(is_rows) >= MIN_BUCKET_TRADES,
    )


def _segment_baseline(rows: list[dict[str, object]]) -> dict[str, float | None]:
    return {
        "avg_return_pct": sum(float(row["return_pct"]) for row in rows) / len(rows) if rows else 0.0,
        "profit_factor": _profit_factor(rows),
    }


def _metric_delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _is_underperforming(
    *,
    trade_count: int,
    net_pnl: float,
    profit_factor: float | None,
    profit_factor_delta: float | None,
    avg_return_delta: float,
) -> bool:
    if trade_count <= 0:
        return False
    if net_pnl < 0 and (profit_factor is None or profit_factor < 1):
        return True
    if profit_factor_delta is not None and profit_factor_delta <= -0.15 and avg_return_delta < 0:
        return True
    return avg_return_delta <= -0.001


def _build_hypotheses(
    buckets: list[TradeAttributionBucket],
    *,
    checks_passed: bool,
) -> list[TradeAttributionHypothesis]:
    hypotheses: list[TradeAttributionHypothesis] = []
    for bucket in buckets:
        if len(hypotheses) >= 5:
            break
        if not bucket.sample_ok or bucket.is_trade_count <= 0:
            continue
        if not bucket.is_underperforming:
            continue
        status = "candidate" if checks_passed and bucket.oos_confirms else "needs_more_data"
        hypotheses.append(
            TradeAttributionHypothesis(
                hypothesis_id=f"{bucket.dimension}:{bucket.bucket_key}",
                description=f"复查 {bucket.dimension} = {bucket.label} 的入场质量",
                evidence=(
                    f"IS {bucket.is_trade_count} 笔，胜率 {bucket.is_win_rate:.1%}，"
                    f"亏损贡献 {bucket.is_loss_contribution:.1%}；"
                    f"OOS {bucket.oos_trade_count} 笔，胜率 {bucket.oos_win_rate:.1%}"
                ),
                risk_note="只作为归因假设；必须用独立 OOS/跨候选复验，不能按最高收益直接定阈值。",
                status=status,
                source_dimension=bucket.dimension,
                source_bucket=bucket.bucket_key,
            )
        )
    return hypotheses


def _anti_overfit_checks(
    *,
    total_trades: int,
    oos_trades: int,
    run_count: int,
    feature_meta_coverage: float,
) -> list[dict[str, object]]:
    return [
        {
            "key": "total_trade_sample",
            "label": "总交易样本",
            "passed": total_trades >= MIN_TOTAL_TRADES,
            "actual": total_trades,
            "required": MIN_TOTAL_TRADES,
        },
        {
            "key": "oos_trade_sample",
            "label": "OOS 交易样本",
            "passed": oos_trades >= MIN_OOS_TRADES,
            "actual": oos_trades,
            "required": MIN_OOS_TRADES,
        },
        {
            "key": "run_count",
            "label": "Run 覆盖",
            "passed": run_count >= MIN_RUN_COUNT,
            "actual": run_count,
            "required": MIN_RUN_COUNT,
        },
        {
            "key": "feature_meta_coverage",
            "label": "信号特征覆盖",
            "passed": feature_meta_coverage >= 0.5,
            "actual": feature_meta_coverage,
            "required": 0.5,
        },
    ]


def _drawdown_trades(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        [row for row in rows if float(row["net_pnl"]) < 0],
        key=lambda row: abs(float(row["net_pnl"])),
        reverse=True,
    )[:20]


def _feature_bucket(feature_name: str, value: float) -> tuple[str, str]:
    if feature_name in {"path_first_bar_adverse", "path_no_favorable_3"}:
        if value >= 0.5:
            label = "首根反向" if feature_name == "path_first_bar_adverse" else "前三根无浮盈"
            return "yes", label
        label = "首根未反向" if feature_name == "path_first_bar_adverse" else "前三根有浮盈"
        return "no", label
    if feature_name == "ema_reclaim":
        return ("yes", "已收回 EMA") if value >= 0.5 else ("no", "未收回 EMA")
    if feature_name in {"local_range_position_20", "volatility_percentile_100"}:
        if value < 0.2:
            return "lt_0_2", f"{feature_name} < 0.2"
        if value < 0.5:
            return "0_2_0_5", f"{feature_name} 0.2-0.5"
        if value < 0.8:
            return "0_5_0_8", f"{feature_name} 0.5-0.8"
        return "gte_0_8", f"{feature_name} >= 0.8"
    if feature_name == "pre_entry_consecutive_move":
        if value <= 0:
            return "none", "连续顺向 0"
        if value <= 2:
            return "1_2", "连续顺向 1-2"
        if value <= 4:
            return "3_4", "连续顺向 3-4"
        return "gte_5", "连续顺向 >= 5"
    if feature_name in {"pre_entry_momentum_3_pct", "pre_entry_momentum_5_pct"}:
        pct = value * 100
        if pct < -1:
            return "lt_neg_1pct", f"{feature_name} < -1%"
        if pct < 0:
            return "neg_1_0pct", f"{feature_name} -1%-0%"
        if pct < 1:
            return "0_1pct", f"{feature_name} 0%-1%"
        if pct < 3:
            return "1_3pct", f"{feature_name} 1%-3%"
        return "gte_3pct", f"{feature_name} >= 3%"
    if feature_name in {"path_mfe_3_stop_r", "path_mae_1_stop_r", "path_mae_3_stop_r"}:
        if value < 0.25:
            return "lt_0_25r", f"{feature_name} < 0.25R"
        if value < 0.5:
            return "0_25_0_5r", f"{feature_name} 0.25-0.5R"
        if value < 1:
            return "0_5_1r", f"{feature_name} 0.5-1R"
        return "gte_1r", f"{feature_name} >= 1R"
    if feature_name in {"stop_distance_pct", "take_profit_distance_pct", "atr_pct", "trend_gap_pct"}:
        pct = value * 100
        if pct < 1:
            return "lt_1pct", f"{feature_name} < 1%"
        if pct < 3:
            return "1_3pct", f"{feature_name} 1%-3%"
        if pct < 6:
            return "3_6pct", f"{feature_name} 3%-6%"
        return "gte_6pct", f"{feature_name} >= 6%"
    if feature_name == "holding_bars":
        if value <= 3:
            return "le_3", "holding <= 3"
        if value <= 12:
            return "4_12", "holding 4-12"
        if value <= 48:
            return "13_48", "holding 13-48"
        return "gt_48", "holding > 48"
    if value < 0.5:
        return "lt_0_5", f"{feature_name} < 0.5"
    if value < 1:
        return "0_5_1", f"{feature_name} 0.5-1"
    if value < 2:
        return "1_2", f"{feature_name} 1-2"
    return "gte_2", f"{feature_name} >= 2"


def _win_rate(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if float(row["net_pnl"]) > 0) / len(rows)


def _profit_factor(rows: list[dict[str, object]]) -> float | None:
    gross_profit = sum(float(row["net_pnl"]) for row in rows if float(row["net_pnl"]) > 0)
    gross_loss = abs(sum(float(row["net_pnl"]) for row in rows if float(row["net_pnl"]) < 0))
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def _feature_meta_coverage(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    covered = 0
    for row in rows:
        features = row.get("features")
        if isinstance(features, dict) and "atr_pct" in features:
            covered += 1
    return covered / len(rows)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric):
        return None
    return numeric
