"""Trade-level attribution readmodels for research candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite

from crypto_backtest_workbench.app.readmodels.research import (
    ParameterGroupView,
    build_parameter_research_workspace,
    build_research_workflow,
)
from crypto_backtest_workbench.app.readmodels.runs import load_run_detail_view
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
    drawdown_trades: tuple[dict[str, object], ...]
    hypotheses: tuple[TradeAttributionHypothesis, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate": self.candidate,
            "summary": self.summary,
            "anti_overfit_checks": list(self.anti_overfit_checks),
            "buckets": [bucket.as_dict() for bucket in self.buckets],
            "drawdown_trades": list(self.drawdown_trades),
            "hypotheses": [hypothesis.as_dict() for hypothesis in self.hypotheses],
        }


def load_research_candidate_trade_attribution(
    run_repository: RunRepository,
    *,
    candidate_id: str,
) -> TradeAttributionView:
    groups = build_parameter_research_workspace(run_repository).parameter_groups
    group = next((item for item in groups if item.group_key == candidate_id), None)
    if group is None:
        raise FileNotFoundError(f"Research candidate not found: {candidate_id}")
    return build_trade_attribution_for_group(run_repository, group=group)


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
            build_trade_attribution_for_group(run_repository, group=group).as_dict()
            for group in groups
        ],
    }


def build_trade_attribution_for_group(
    run_repository: RunRepository,
    *,
    group: ParameterGroupView,
) -> TradeAttributionView:
    trade_rows: list[dict[str, object]] = []
    for run_id in group.run_ids:
        try:
            detail = load_run_detail_view(run_repository, run_id)
        except FileNotFoundError:
            continue
        oos_start = _segment_start(detail.validation_summary, "oos_segment")
        for trade in detail.execution.trades:
            features = _trade_features(trade)
            trade_rows.append(
                {
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
                    "segment": "oos" if oos_start is not None and trade.entry_time >= oos_start else "is",
                    "labels": _trade_labels(trade.net_pnl),
                    "features": features,
                }
            )

    total_trades = len(trade_rows)
    oos_trades = sum(1 for row in trade_rows if row["segment"] == "oos")
    run_count = len({str(row["run_id"]) for row in trade_rows})
    total_net_pnl = sum(float(row["net_pnl"]) for row in trade_rows)
    losses = [abs(float(row["net_pnl"])) for row in trade_rows if float(row["net_pnl"]) < 0]
    total_loss_abs = sum(losses)
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
    buckets = _build_buckets(enriched_rows, total_loss_abs=total_loss_abs)
    hypotheses = _build_hypotheses(buckets, checks_passed=all(bool(check["passed"]) for check in checks))
    summary = {
        "run_count": run_count,
        "trade_count": total_trades,
        "oos_trade_count": oos_trades,
        "win_rate": _win_rate(enriched_rows),
        "net_pnl": total_net_pnl,
        "profit_factor": _profit_factor(enriched_rows),
        "feature_meta_coverage": _feature_meta_coverage(enriched_rows),
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


def _trade_features(trade) -> dict[str, float]:
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
    return features


def _trade_labels(net_pnl: float) -> list[str]:
    if net_pnl > 0:
        return ["winner"]
    if net_pnl < 0:
        return ["loser"]
    return ["flat"]


def _build_buckets(rows: list[dict[str, object]], *, total_loss_abs: float) -> list[TradeAttributionBucket]:
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
            ):
                value = _finite_float(features.get(feature_name))
                if value is None:
                    continue
                bucket_key, label = _feature_bucket(feature_name, value)
                _append_bucket(bucket_rows, feature_name, bucket_key, label, row)

    buckets = [
        _summarize_bucket(dimension, bucket_key, label, entries, total_loss_abs=total_loss_abs)
        for (dimension, bucket_key, label), entries in bucket_rows.items()
    ]
    return sorted(
        buckets,
        key=lambda item: (item.loss_contribution, -item.net_pnl if item.net_pnl < 0 else 0, item.trade_count),
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


def _summarize_bucket(
    dimension: str,
    bucket_key: str,
    label: str,
    rows: list[dict[str, object]],
    *,
    total_loss_abs: float,
) -> TradeAttributionBucket:
    losses = [abs(float(row["net_pnl"])) for row in rows if float(row["net_pnl"]) < 0]
    loss_abs = sum(losses)
    return TradeAttributionBucket(
        dimension=dimension,
        bucket_key=bucket_key,
        label=label,
        trade_count=len(rows),
        oos_trade_count=sum(1 for row in rows if row["segment"] == "oos"),
        win_rate=_win_rate(rows),
        net_pnl=sum(float(row["net_pnl"]) for row in rows),
        avg_return_pct=sum(float(row["return_pct"]) for row in rows) / len(rows) if rows else 0.0,
        profit_factor=_profit_factor(rows),
        loss_contribution=loss_abs / total_loss_abs if total_loss_abs > 0 else 0.0,
        big_loss_count=sum(1 for row in rows if "big_loss" in row.get("labels", [])),
        sample_ok=len(rows) >= MIN_BUCKET_TRADES,
    )


def _build_hypotheses(
    buckets: list[TradeAttributionBucket],
    *,
    checks_passed: bool,
) -> list[TradeAttributionHypothesis]:
    hypotheses: list[TradeAttributionHypothesis] = []
    for bucket in buckets:
        if len(hypotheses) >= 5:
            break
        if not bucket.sample_ok or bucket.trade_count <= 0:
            continue
        if bucket.net_pnl >= 0 and bucket.loss_contribution < 0.25:
            continue
        status = "candidate" if checks_passed and bucket.oos_trade_count >= 3 else "needs_more_data"
        hypotheses.append(
            TradeAttributionHypothesis(
                hypothesis_id=f"{bucket.dimension}:{bucket.bucket_key}",
                description=f"复查 {bucket.dimension} = {bucket.label} 的入场质量",
                evidence=(
                    f"{bucket.trade_count} 笔交易，OOS {bucket.oos_trade_count} 笔，"
                    f"胜率 {bucket.win_rate:.1%}，亏损贡献 {bucket.loss_contribution:.1%}"
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
