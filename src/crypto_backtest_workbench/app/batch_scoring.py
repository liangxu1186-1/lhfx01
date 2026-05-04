"""Batch parameter-group scoring and recommendation rules."""

from __future__ import annotations

MAX_IS_OOS_GAP = 0.2
MIN_OOS_TRADES = 1


BATCH_RECOMMENDATION_RULES: dict[str, dict[str, object]] = {
    "robust_candidate": {
        "label": "自动稳健候选",
        "summary": "跨快照表现稳定，样本内外收益、回撤、样本外交易数和邻域稳定度同时达标。",
        "thresholds": [
            "覆盖快照数 >= 2",
            "正收益占比 >= 60%",
            "平均收益率 > 0",
            "平均超额收益 > 0",
            "必须存在样本外数据",
            "平均样本外收益 > 0",
            "平均样本外超额 > 0",
            "样本外正收益占比 >= 50%",
            f"最少样本外交易数 >= {MIN_OOS_TRADES}",
            f"样本内外收益差 <= {MAX_IS_OOS_GAP * 100:.0f}%",
            "平均最大回撤 <= 35%",
            "最少交易数 >= 3",
            "相邻参数稳定度 >= 50%，且至少有 1 个稳定邻居",
        ],
        "min_snapshot_count": 2,
        "min_positive_ratio": 0.6,
        "min_trade_count": 3,
        "min_oos_trade_count": MIN_OOS_TRADES,
        "max_is_oos_gap": MAX_IS_OOS_GAP,
        "max_avg_drawdown": 0.35,
        "min_neighbor_stability": 0.5,
        "min_stable_neighbor_count": 1,
        "min_oos_positive_ratio": 0.5,
    },
    "high_return_candidate": {
        "label": "自动高收益候选",
        "summary": "收益上限足够高，但稳定性还没有达到稳健候选标准。",
        "thresholds": [
            "最佳收益率 > 0",
            "平均收益率 > 0",
            "平均样本外收益 > 0",
            f"最少样本外交易数 >= {MIN_OOS_TRADES}",
            "未命中自动排除",
            "且未命中自动稳健候选",
        ],
        "min_oos_trade_count": MIN_OOS_TRADES,
    },
    "excluded_combination": {
        "label": "自动排除",
        "summary": "平均收益或样本外正收益表现明显不达标，应优先排除。",
        "thresholds": [
            "平均收益率 <= 0，或",
            "正收益占比 = 0，或",
            "最差最大回撤 >= 80%，或",
            "存在样本外数据且样本外正收益占比 = 0",
        ],
    },
}


def build_batch_scoring_rules() -> dict[str, dict[str, object]]:
    return {
        key: {
            "label": value["label"],
            "summary": value["summary"],
            "thresholds": list(value["thresholds"]),
        }
        for key, value in BATCH_RECOMMENDATION_RULES.items()
    }


def build_batch_recommendations(
    run_rows: list[dict[str, object]],
    *,
    strategy_name: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]], dict[str, dict[str, object]]]:
    if strategy_name is not None:
        run_rows = [row for row in run_rows if row.get("strategy_name") == strategy_name]
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for row in run_rows:
        row_strategy_name = str(row.get("strategy_name") or "ema_crossover")
        leverage = _as_optional_float(row.get("leverage"))
        key = _parameter_group_key(row)
        params = _parameter_group_params(row)
        group = grouped.setdefault(
            key,
            {
                **params,
                "strategy_name": row_strategy_name,
                "parameter_summary": _parameter_summary(row),
                "signal_filter_summary": row.get("signal_filter_summary"),
                "leverage": leverage,
                "run_count": 0,
                "positive_run_count": 0,
                "oos_positive_run_count": 0,
                "oos_available_count": 0,
                "avg_total_return": 0.0,
                "avg_excess_return": 0.0,
                "avg_oos_total_return": 0.0,
                "avg_oos_excess_return": 0.0,
                "avg_max_drawdown": 0.0,
                "worst_max_drawdown": 0.0,
                "best_total_return": float("-inf"),
                "min_trade_count": None,
                "min_oos_trade_count": None,
                "snapshot_ids": set(),
                "timeframes": set(),
                "run_ids": [],
                "neighbor_count": 0,
                "stable_neighbor_count": 0,
                "neighbor_stability_score": None,
            },
        )
        total_return = float(row.get("total_return", 0.0))
        excess_return = row.get("excess_return")
        oos_total_return = row.get("oos_total_return")
        oos_excess_return = row.get("oos_excess_return")
        oos_trade_count = row.get("oos_trade_count")
        max_drawdown = float(row.get("max_drawdown", 0.0))
        trade_count = int(row.get("trade_count", 0))
        group["run_count"] = int(group["run_count"]) + 1
        if total_return > 0:
            group["positive_run_count"] = int(group["positive_run_count"]) + 1
        if oos_total_return is not None:
            group["oos_available_count"] = int(group["oos_available_count"]) + 1
            if float(oos_total_return) > 0:
                group["oos_positive_run_count"] = int(group["oos_positive_run_count"]) + 1
        group["avg_total_return"] = float(group["avg_total_return"]) + total_return
        group["avg_excess_return"] = float(group["avg_excess_return"]) + (float(excess_return) if excess_return is not None else 0.0)
        group["avg_oos_total_return"] = float(group["avg_oos_total_return"]) + (float(oos_total_return) if oos_total_return is not None else 0.0)
        group["avg_oos_excess_return"] = float(group["avg_oos_excess_return"]) + (float(oos_excess_return) if oos_excess_return is not None else 0.0)
        group["avg_max_drawdown"] = float(group["avg_max_drawdown"]) + max_drawdown
        group["worst_max_drawdown"] = max(float(group["worst_max_drawdown"]), max_drawdown)
        group["best_total_return"] = max(float(group["best_total_return"]), total_return)
        min_trade_count = group["min_trade_count"]
        group["min_trade_count"] = trade_count if min_trade_count is None else min(int(min_trade_count), trade_count)
        min_oos_trade_count = group["min_oos_trade_count"]
        if oos_trade_count is not None:
            group["min_oos_trade_count"] = int(oos_trade_count) if min_oos_trade_count is None else min(int(min_oos_trade_count), int(oos_trade_count))
        snapshot_ids = group["snapshot_ids"]
        timeframes = group["timeframes"]
        run_ids = group["run_ids"]
        if isinstance(snapshot_ids, set):
            snapshot_ids.add(str(row.get("dataset_snapshot_id", "")))
        if isinstance(timeframes, set):
            timeframes.add(str(row.get("timeframe", "")))
        if isinstance(run_ids, list):
            run_ids.append(str(row.get("run_id", "")))

    fast_values = sorted({group["fast_period"] for group in grouped.values() if group.get("fast_period") is not None})
    slow_values = sorted({group["slow_period"] for group in grouped.values() if group.get("slow_period") is not None})
    leverage_values = sorted({group["leverage"] for group in grouped.values() if group.get("leverage") is not None})
    fast_index = {value: index for index, value in enumerate(fast_values)}
    slow_index = {value: index for index, value in enumerate(slow_values)}
    leverage_index = {value: index for index, value in enumerate(leverage_values)}
    key_by_comparable = {
        (
            group.get("strategy_name"),
            group.get("fast_period"),
            group.get("slow_period"),
            group.get("leverage"),
        ): key
        for key, group in grouped.items()
    }

    def averaged_metric(group: dict[str, object], field_name: str) -> float:
        return float(group[field_name]) / int(group["run_count"])

    def oos_positive_ratio_for_group(group: dict[str, object]) -> float | None:
        oos_available_count = int(group["oos_available_count"])
        if oos_available_count == 0:
            return None
        return int(group["oos_positive_run_count"]) / oos_available_count

    def is_stable_group(candidate: dict[str, object]) -> bool:
        if averaged_metric(candidate, "avg_total_return") <= 0 or averaged_metric(candidate, "avg_excess_return") <= 0:
            return False
        if averaged_metric(candidate, "avg_max_drawdown") >= 0.8:
            return False
        return (
            int(candidate["oos_available_count"]) > 0
            and averaged_metric(candidate, "avg_oos_total_return") > 0
            and averaged_metric(candidate, "avg_oos_excess_return") > 0
            and float(oos_positive_ratio_for_group(candidate) or 0.0) > 0
            and int(candidate["min_oos_trade_count"] or 0) >= MIN_OOS_TRADES
        )

    for key, group in grouped.items():
        fast_period = group.get("fast_period")
        slow_period = group.get("slow_period")
        leverage = group.get("leverage")
        group_strategy_name = group.get("strategy_name")
        neighbors: list[dict[str, object]] = []
        if fast_period is not None and slow_period is not None:
            current_fast_index = fast_index.get(fast_period)
            current_slow_index = slow_index.get(slow_period)
            if current_fast_index is not None:
                for offset in (-1, 1):
                    next_index = current_fast_index + offset
                    if 0 <= next_index < len(fast_values):
                        neighbor_key = key_by_comparable.get((group_strategy_name, fast_values[next_index], slow_period, leverage))
                        neighbor = grouped.get(neighbor_key) if neighbor_key is not None else None
                        if neighbor is not None:
                            neighbors.append(neighbor)
            if current_slow_index is not None:
                for offset in (-1, 1):
                    next_index = current_slow_index + offset
                    if 0 <= next_index < len(slow_values):
                        neighbor_key = key_by_comparable.get((group_strategy_name, fast_period, slow_values[next_index], leverage))
                        neighbor = grouped.get(neighbor_key) if neighbor_key is not None else None
                        if neighbor is not None:
                            neighbors.append(neighbor)
        if leverage is not None:
            current_leverage_index = leverage_index.get(leverage)
            if current_leverage_index is not None:
                for offset in (-1, 1):
                    next_index = current_leverage_index + offset
                    if 0 <= next_index < len(leverage_values):
                        neighbor_key = key_by_comparable.get((group_strategy_name, fast_period, slow_period, leverage_values[next_index]))
                        neighbor = grouped.get(neighbor_key) if neighbor_key is not None else None
                        if neighbor is not None:
                            neighbors.append(neighbor)
        stable_neighbor_count = sum(1 for neighbor in neighbors if is_stable_group(neighbor))
        group["neighbor_count"] = len(neighbors)
        group["stable_neighbor_count"] = stable_neighbor_count
        group["neighbor_stability_score"] = stable_neighbor_count / len(neighbors) if neighbors else None

    parameter_groups: list[dict[str, object]] = []
    for group in grouped.values():
        run_count = int(group["run_count"])
        avg_total_return = float(group["avg_total_return"]) / run_count
        avg_excess_return = float(group["avg_excess_return"]) / run_count
        avg_oos_total_return = float(group["avg_oos_total_return"]) / run_count
        avg_oos_excess_return = float(group["avg_oos_excess_return"]) / run_count
        avg_max_drawdown = float(group["avg_max_drawdown"]) / run_count
        worst_max_drawdown = float(group["worst_max_drawdown"])
        return_over_drawdown = avg_total_return / avg_max_drawdown if avg_max_drawdown > 0 else (avg_total_return if avg_total_return > 0 else 0.0)
        is_oos_gap = avg_total_return - avg_oos_total_return if int(group["oos_available_count"]) else None
        positive_ratio = int(group["positive_run_count"]) / run_count
        oos_available_count = int(group["oos_available_count"])
        oos_positive_ratio = int(group["oos_positive_run_count"]) / oos_available_count if oos_available_count else None
        neighbor_stability_score = group["neighbor_stability_score"]
        confidence_components = [
            0.25 * _score_metric(len(group["snapshot_ids"]), 3.0),
            0.25 * float(neighbor_stability_score or 0.0),
            0.2 * positive_ratio,
            0.15 * _score_metric(int(group["min_trade_count"] or 0), 10.0),
            0.15
            * (
                _score_metric(avg_oos_total_return, 0.2) * 0.5 + float(oos_positive_ratio or 0.0) * 0.5
                if oos_available_count
                else 0.0
            ),
        ]
        confidence = round(sum(confidence_components) * 100, 1)
        return_weights = [
            ("avg_total_return", avg_total_return, 0.35, 0.3),
            ("avg_excess_return", avg_excess_return, 0.2, 0.2),
            ("avg_oos_total_return", avg_oos_total_return, 0.25, 0.2),
            ("avg_oos_excess_return", avg_oos_excess_return, 0.1, 0.15),
            ("best_total_return", float(group["best_total_return"]), 0.1, 0.5),
        ]
        weighted_return_score = 0.0
        active_weight_sum = 0.0
        for metric_name, metric_value, weight, target in return_weights:
            if metric_name in {"avg_oos_total_return", "avg_oos_excess_return"} and not oos_available_count:
                continue
            weighted_return_score += weight * _score_metric(metric_value, target)
            active_weight_sum += weight
        normalized_return_score = (weighted_return_score / active_weight_sum) if active_weight_sum else 0.0
        drawdown_penalty = _clamp_score(avg_max_drawdown / 0.8)
        risk_reward_score = _score_metric(return_over_drawdown, 2.0)
        score = round(
            (0.45 * normalized_return_score + 0.25 * risk_reward_score + 0.3 * (confidence / 100.0))
            * (1 - 0.35 * drawdown_penalty)
            * 100,
            1,
        )
        parameter_groups.append(
            {
                "strategy_name": group["strategy_name"],
                "parameter_summary": group["parameter_summary"],
                "signal_filter_summary": group.get("signal_filter_summary"),
                "fast_period": group["fast_period"],
                "slow_period": group["slow_period"],
                "trend_fast_period": group.get("trend_fast_period"),
                "trend_slow_period": group.get("trend_slow_period"),
                "entry_ema_period": group.get("entry_ema_period"),
                "atr_period": group.get("atr_period"),
                "atr_entry_tolerance": group.get("atr_entry_tolerance"),
                "atr_stop_mult": group.get("atr_stop_mult"),
                "risk_reward_ratio": group.get("risk_reward_ratio"),
                "leverage": group["leverage"],
                "run_count": run_count,
                "snapshot_count": len(group["snapshot_ids"]),
                "timeframe_count": len(group["timeframes"]),
                "avg_total_return": avg_total_return,
                "avg_excess_return": avg_excess_return,
                "avg_oos_total_return": avg_oos_total_return,
                "avg_oos_excess_return": avg_oos_excess_return,
                "is_oos_gap": is_oos_gap,
                "avg_max_drawdown": avg_max_drawdown,
                "worst_max_drawdown": worst_max_drawdown,
                "return_over_drawdown": return_over_drawdown,
                "best_total_return": group["best_total_return"],
                "min_trade_count": group["min_trade_count"],
                "min_oos_trade_count": group["min_oos_trade_count"],
                "positive_ratio": positive_ratio,
                "oos_available_count": oos_available_count,
                "oos_positive_ratio": oos_positive_ratio,
                "neighbor_count": group["neighbor_count"],
                "stable_neighbor_count": group["stable_neighbor_count"],
                "neighbor_stability_score": neighbor_stability_score,
                "score": score,
                "confidence": confidence,
                "run_ids": group["run_ids"],
            }
        )

    robust_rule = BATCH_RECOMMENDATION_RULES["robust_candidate"]
    robust_candidates = [
        {
            **group,
            "reason": (
                "命中稳健候选："
                f"覆盖 {group['snapshot_count']} 个快照，"
                f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"平均样本外收益 {float(group['avg_oos_total_return']) * 100:.2f}%，"
                f"平均样本外超额 {float(group['avg_oos_excess_return']) * 100:.2f}%，"
                f"样本内外收益差 {float(group['is_oos_gap'] or 0.0) * 100:.2f}%，"
                f"平均最大回撤 {float(group['avg_max_drawdown']) * 100:.2f}%，"
                f"最少交易数 {int(group['min_trade_count'] or 0)}，"
                f"最少样本外交易数 {int(group['min_oos_trade_count'] or 0)}。"
            ),
        }
        for group in parameter_groups
        if group["snapshot_count"] >= int(robust_rule["min_snapshot_count"])
        and group["positive_ratio"] >= float(robust_rule["min_positive_ratio"])
        and float(group["avg_total_return"]) > 0
        and float(group["avg_excess_return"]) > 0
        and int(group["oos_available_count"]) > 0
        and float(group["avg_oos_total_return"]) > 0
        and float(group["avg_oos_excess_return"]) > 0
        and float(group["oos_positive_ratio"] or 0.0) >= float(robust_rule["min_oos_positive_ratio"])
        and int(group["min_oos_trade_count"] or 0) >= int(robust_rule["min_oos_trade_count"])
        and float(group["is_oos_gap"] or 0.0) <= float(robust_rule["max_is_oos_gap"])
        and float(group["avg_max_drawdown"]) <= float(robust_rule["max_avg_drawdown"])
        and int(group["min_trade_count"] or 0) >= int(robust_rule["min_trade_count"])
        and int(group["stable_neighbor_count"]) >= int(robust_rule["min_stable_neighbor_count"])
        and float(group["neighbor_stability_score"] or 0.0) >= float(robust_rule["min_neighbor_stability"])
    ]
    robust_keys = {_recommendation_key(item) for item in robust_candidates}
    excluded_keys = {
        _recommendation_key(group)
        for group in parameter_groups
        if (
            float(group["avg_total_return"]) <= 0
            or float(group["positive_ratio"]) == 0
            or float(group["worst_max_drawdown"]) >= 0.8
            or (group["oos_available_count"] and float(group["oos_positive_ratio"] or 0.0) == 0)
        )
    }
    high_return_candidates = [
        {
            **group,
            "reason": (
                "命中高收益候选："
                f"最佳收益率 {float(group['best_total_return']) * 100:.2f}%，"
                f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                f"平均最大回撤 {float(group['avg_max_drawdown']) * 100:.2f}%，"
                f"收益回撤比 {float(group['return_over_drawdown']):.2f}，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"样本外收益 {float(group['avg_oos_total_return']) * 100:.2f}%。"
                " 收益上限高，但稳定性还没有达到稳健候选标准。"
            ),
        }
        for group in parameter_groups
        if float(group["best_total_return"]) > 0
        and float(group["avg_total_return"]) > 0
        and int(group["oos_available_count"]) > 0
        and float(group["avg_oos_total_return"]) > 0
        and int(group["min_oos_trade_count"] or 0) >= int(BATCH_RECOMMENDATION_RULES["high_return_candidate"]["min_oos_trade_count"])
        and _recommendation_key(group) not in robust_keys
        and _recommendation_key(group) not in excluded_keys
    ]
    excluded_combinations = [
        {
            **group,
            "reason": (
                "命中排除规则："
                f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                f"最差最大回撤 {float(group['worst_max_drawdown']) * 100:.2f}%，"
                f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                f"样本外正收益占比 {(float(group['oos_positive_ratio']) * 100):.0f}%"
                if group["oos_positive_ratio"] is not None
                else (
                    "命中排除规则："
                    f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                    f"正收益占比 {float(group['positive_ratio']) * 100:.0f}%，"
                    f"最差最大回撤 {float(group['worst_max_drawdown']) * 100:.2f}%，"
                    f"相邻参数稳定度 {(float(group['neighbor_stability_score'] or 0.0) * 100):.0f}%，"
                    f"总分 {float(group['score']):.1f}，置信度 {float(group['confidence']):.1f}，"
                    "当前没有样本外正收益记录。"
                )
            ),
        }
        for group in parameter_groups
        if (
            float(group["avg_total_return"]) <= 0
            or float(group["positive_ratio"]) == 0
            or float(group["worst_max_drawdown"]) >= 0.8
            or (group["oos_available_count"] and float(group["oos_positive_ratio"] or 0.0) == 0)
        )
    ]
    exploratory_candidates = [
        {
            **group,
            "reason": (
                "命中探索候选："
                f"最佳收益率 {float(group['best_total_return']) * 100:.2f}%，"
                f"平均收益率 {float(group['avg_total_return']) * 100:.2f}%，"
                "当前没有足够样本外交易记录，不能进入稳健或高收益候选。"
            ),
        }
        for group in parameter_groups
        if float(group["best_total_return"]) > 0
        and float(group["avg_total_return"]) > 0
        and int(group["oos_available_count"]) == 0
        and _recommendation_key(group) not in robust_keys
        and _recommendation_key(group) not in excluded_keys
    ]

    parameter_groups.sort(
        key=lambda item: (
            float(item["score"]),
            float(item["confidence"]),
            float(item["avg_oos_excess_return"]),
            float(item["avg_excess_return"]),
        ),
        reverse=True,
    )
    robust_candidates.sort(
        key=lambda item: (float(item["confidence"]), float(item["score"]), float(item["avg_oos_excess_return"])),
        reverse=True,
    )
    high_return_candidates.sort(
        key=lambda item: (float(item["score"]), float(item["best_total_return"]), float(item["confidence"])),
        reverse=True,
    )
    excluded_combinations.sort(key=lambda item: (float(item["score"]), float(item["confidence"])))
    exploratory_candidates.sort(
        key=lambda item: (float(item["score"]), float(item["best_total_return"]), float(item["confidence"])),
        reverse=True,
    )

    return (
        parameter_groups,
        {
            "robust_candidates": robust_candidates[:5],
            "high_return_candidates": high_return_candidates[:5],
            "exploratory_candidates": exploratory_candidates[:5],
            "excluded_combinations": excluded_combinations[:5],
        },
        build_batch_scoring_rules(),
    )


def _clamp_score(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _score_metric(value: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return _clamp_score(value / target)


def _as_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _parameter_group_key(row: dict[str, object]) -> tuple[object, ...]:
    strategy_name = str(row.get("strategy_name") or "ema_crossover")
    leverage = _as_optional_float(row.get("leverage"))
    if strategy_name == "ema_pullback_atr_v2":
        return (
            strategy_name,
            _as_optional_int(row.get("trend_fast_period")),
            _as_optional_int(row.get("trend_slow_period")),
            _as_optional_int(row.get("entry_ema_period")),
            _as_optional_int(row.get("atr_period")),
            _as_optional_float(row.get("atr_entry_tolerance")),
            _as_optional_float(row.get("atr_stop_mult")),
            _as_optional_float(row.get("risk_reward_ratio")),
            row.get("signal_filter_summary"),
            leverage,
        )
    return (
        strategy_name,
        _as_optional_int(row.get("fast_period")),
        _as_optional_int(row.get("slow_period")),
        leverage,
    )


def _parameter_group_params(row: dict[str, object]) -> dict[str, object]:
    strategy_name = str(row.get("strategy_name") or "ema_crossover")
    if strategy_name == "ema_pullback_atr_v2":
        return {
            "fast_period": _as_optional_int(row.get("trend_fast_period")),
            "slow_period": _as_optional_int(row.get("trend_slow_period")),
            "trend_fast_period": _as_optional_int(row.get("trend_fast_period")),
            "trend_slow_period": _as_optional_int(row.get("trend_slow_period")),
            "entry_ema_period": _as_optional_int(row.get("entry_ema_period")),
            "atr_period": _as_optional_int(row.get("atr_period")),
            "atr_entry_tolerance": _as_optional_float(row.get("atr_entry_tolerance")),
            "atr_stop_mult": _as_optional_float(row.get("atr_stop_mult")),
            "risk_reward_ratio": _as_optional_float(row.get("risk_reward_ratio")),
            "signal_filter_summary": row.get("signal_filter_summary"),
        }
    return {
        "fast_period": _as_optional_int(row.get("fast_period")),
        "slow_period": _as_optional_int(row.get("slow_period")),
    }


def _parameter_summary(row: dict[str, object]) -> str:
    summary = row.get("parameter_summary")
    if isinstance(summary, str) and summary:
        return summary
    return ":".join(str(part) for part in _parameter_group_key(row)[1:] if part is not None)


def _recommendation_key(group: dict[str, object]) -> tuple[object, ...]:
    if group.get("strategy_name") == "ema_pullback_atr_v2":
        return (
            group.get("strategy_name"),
            group.get("trend_fast_period"),
            group.get("trend_slow_period"),
            group.get("entry_ema_period"),
            group.get("atr_period"),
            group.get("atr_entry_tolerance"),
            group.get("atr_stop_mult"),
            group.get("risk_reward_ratio"),
            group.get("leverage"),
        )
    return (
        group.get("strategy_name"),
        group.get("fast_period"),
        group.get("slow_period"),
        group.get("leverage"),
    )
