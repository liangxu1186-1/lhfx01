from __future__ import annotations

from crypto_backtest_workbench.app.batch_scoring import build_batch_recommendations, build_batch_scoring_rules


def test_build_batch_recommendations_keeps_high_return_and_excluded_mutually_exclusive() -> None:
    run_rows = [
        *_rows_for_group(
            fast_period=2,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.12, 0.08),
            excess_returns=(0.06, 0.05),
            oos_total_returns=(0.05, 0.04),
            oos_excess_returns=(0.03, 0.02),
            max_drawdowns=(0.85, 0.82),
            trade_counts=(6, 5),
        ),
        *_rows_for_group(
            fast_period=3,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.18, 0.16),
            excess_returns=(0.09, 0.08),
            oos_total_returns=(0.06, 0.05),
            oos_excess_returns=(0.03, 0.02),
            max_drawdowns=(0.24, 0.22),
            trade_counts=(8, 7),
        ),
        *_rows_for_group(
            fast_period=4,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.15, 0.13),
            excess_returns=(0.07, 0.06),
            oos_total_returns=(0.05, 0.04),
            oos_excess_returns=(0.02, 0.02),
            max_drawdowns=(0.23, 0.21),
            trade_counts=(7, 7),
        ),
        *_rows_for_group(
            fast_period=7,
            slow_period=10,
            leverage=2.0,
            snapshot_ids=("snapshot-a",),
            total_returns=(0.32,),
            excess_returns=(0.18,),
            oos_total_returns=(0.04,),
            oos_excess_returns=(0.01,),
            max_drawdowns=(0.41,),
            trade_counts=(4,),
        ),
    ]

    parameter_groups, recommendations, scoring_rules = build_batch_recommendations(run_rows)

    assert len(parameter_groups) == 4
    assert set(scoring_rules) == {"robust_candidate", "high_return_candidate", "excluded_combination"}

    excluded_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["excluded_combinations"]
    }
    high_return_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["high_return_candidates"]
    }
    robust_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["robust_candidates"]
    }

    assert (2, 5, 1.0) in excluded_keys
    assert (2, 5, 1.0) not in high_return_keys
    assert (3, 5, 1.0) in robust_keys
    assert (4, 5, 1.0) in robust_keys
    assert (7, 10, 2.0) in high_return_keys
    assert all(item["avg_oos_total_return"] > 0 for item in recommendations["high_return_candidates"])
    assert all((item["min_oos_trade_count"] or 0) >= 1 for item in recommendations["high_return_candidates"])


def test_build_batch_recommendations_groups_by_leverage_and_computes_neighbor_stability() -> None:
    run_rows = [
        *_rows_for_group(
            fast_period=2,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.11, 0.10),
            excess_returns=(0.05, 0.05),
            oos_total_returns=(0.04, 0.04),
            oos_excess_returns=(0.02, 0.02),
            max_drawdowns=(0.18, 0.17),
            trade_counts=(7, 7),
        ),
        *_rows_for_group(
            fast_period=2,
            slow_period=5,
            leverage=2.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.16, 0.14),
            excess_returns=(0.08, 0.07),
            oos_total_returns=(0.05, 0.04),
            oos_excess_returns=(0.03, 0.02),
            max_drawdowns=(0.22, 0.20),
            trade_counts=(8, 8),
        ),
        *_rows_for_group(
            fast_period=3,
            slow_period=5,
            leverage=2.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.18, 0.16),
            excess_returns=(0.09, 0.08),
            oos_total_returns=(0.07, 0.06),
            oos_excess_returns=(0.03, 0.03),
            max_drawdowns=(0.23, 0.21),
            trade_counts=(8, 7),
        ),
    ]

    parameter_groups, recommendations, _ = build_batch_recommendations(run_rows)
    group_by_key = {
        (item["fast_period"], item["slow_period"], item["leverage"]): item
        for item in parameter_groups
    }

    assert set(group_by_key) == {(2, 5, 1.0), (2, 5, 2.0), (3, 5, 2.0)}
    assert group_by_key[(2, 5, 2.0)]["neighbor_count"] == 2
    assert group_by_key[(2, 5, 2.0)]["stable_neighbor_count"] == 2
    assert group_by_key[(2, 5, 2.0)]["neighbor_stability_score"] == 1.0
    assert group_by_key[(2, 5, 2.0)]["snapshot_count"] == 2
    assert recommendations["robust_candidates"][0]["neighbor_stability_score"] == 1.0
    assert recommendations["robust_candidates"][0]["is_oos_gap"] is not None


def test_build_batch_recommendations_requires_oos_for_stable_and_high_return_candidates() -> None:
    run_rows = [
        *_rows_for_group(
            fast_period=2,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.18, 0.16),
            excess_returns=(0.08, 0.07),
            oos_total_returns=(None, None),
            oos_excess_returns=(None, None),
            max_drawdowns=(0.22, 0.20),
            trade_counts=(8, 7),
            oos_trade_counts=(None, None),
        ),
        *_rows_for_group(
            fast_period=3,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.15, 0.14),
            excess_returns=(0.07, 0.06),
            oos_total_returns=(0.04, 0.03),
            oos_excess_returns=(0.02, 0.02),
            max_drawdowns=(0.21, 0.19),
            trade_counts=(7, 7),
        ),
    ]

    parameter_groups, recommendations, _ = build_batch_recommendations(run_rows)
    group_by_key = {
        (item["fast_period"], item["slow_period"], item["leverage"]): item
        for item in parameter_groups
    }
    robust_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["robust_candidates"]
    }
    high_return_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["high_return_candidates"]
    }
    exploratory_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["exploratory_candidates"]
    }

    assert group_by_key[(2, 5, 1.0)]["oos_available_count"] == 0
    assert group_by_key[(2, 5, 1.0)]["is_oos_gap"] is None
    assert (2, 5, 1.0) not in robust_keys
    assert (2, 5, 1.0) not in high_return_keys
    assert (2, 5, 1.0) in exploratory_keys


def test_build_batch_recommendations_rejects_large_is_oos_gap_from_stable_candidates() -> None:
    run_rows = [
        *_rows_for_group(
            fast_period=2,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.42, 0.40),
            excess_returns=(0.20, 0.19),
            oos_total_returns=(0.04, 0.03),
            oos_excess_returns=(0.02, 0.02),
            max_drawdowns=(0.24, 0.22),
            trade_counts=(8, 8),
        ),
        *_rows_for_group(
            fast_period=3,
            slow_period=5,
            leverage=1.0,
            snapshot_ids=("snapshot-a", "snapshot-b"),
            total_returns=(0.16, 0.15),
            excess_returns=(0.08, 0.07),
            oos_total_returns=(0.05, 0.04),
            oos_excess_returns=(0.02, 0.02),
            max_drawdowns=(0.20, 0.19),
            trade_counts=(7, 7),
        ),
    ]

    parameter_groups, recommendations, _ = build_batch_recommendations(run_rows)
    gap_group = next(item for item in parameter_groups if item["fast_period"] == 2)
    robust_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["robust_candidates"]
    }
    high_return_keys = {
        (item["fast_period"], item["slow_period"], item["leverage"])
        for item in recommendations["high_return_candidates"]
    }

    assert gap_group["is_oos_gap"] is not None
    assert gap_group["is_oos_gap"] > 0.2
    assert (2, 5, 1.0) not in robust_keys
    assert (2, 5, 1.0) in high_return_keys


def test_build_batch_scoring_rules_hide_internal_threshold_fields() -> None:
    rules = build_batch_scoring_rules()

    assert set(rules) == {"robust_candidate", "high_return_candidate", "excluded_combination"}
    assert "min_snapshot_count" not in rules["robust_candidate"]
    assert rules["robust_candidate"]["label"] == "自动稳健候选"
    assert "必须存在样本外数据" in rules["robust_candidate"]["thresholds"]
    assert "平均样本外收益 > 0" in rules["high_return_candidate"]["thresholds"]


def test_build_batch_recommendations_groups_v1_and_v2_separately() -> None:
    run_rows = [
        *_rows_for_group(
            fast_period=8,
            slow_period=34,
            leverage=1.0,
            snapshot_ids=("snapshot-a",),
            total_returns=(0.1,),
            excess_returns=(0.05,),
            oos_total_returns=(0.03,),
            oos_excess_returns=(0.02,),
            max_drawdowns=(0.1,),
            trade_counts=(4,),
        ),
        {
            **_rows_for_group(
                fast_period=8,
                slow_period=34,
                leverage=1.0,
                snapshot_ids=("snapshot-b",),
                total_returns=(0.2,),
                excess_returns=(0.08,),
                oos_total_returns=(0.04,),
                oos_excess_returns=(0.03,),
                max_drawdowns=(0.12,),
                trade_counts=(5,),
            )[0],
            "strategy_name": "ema_pullback_atr_v2",
            "trend_fast_period": 8,
            "trend_slow_period": 34,
            "entry_ema_period": 21,
            "atr_period": 14,
            "atr_entry_tolerance": 0.5,
            "atr_stop_mult": 1.5,
            "risk_reward_ratio": 2.0,
        },
    ]

    parameter_groups, _, _ = build_batch_recommendations(run_rows)

    assert len(parameter_groups) == 2
    assert {group["strategy_name"] for group in parameter_groups} == {"ema_crossover", "ema_pullback_atr_v2"}
    v2_group = next(group for group in parameter_groups if group["strategy_name"] == "ema_pullback_atr_v2")
    assert v2_group["trend_fast_period"] == 8
    assert v2_group["atr_stop_mult"] == 1.5


def _rows_for_group(
    *,
    fast_period: int,
    slow_period: int,
    leverage: float,
    snapshot_ids: tuple[str, ...],
    total_returns: tuple[float, ...],
    excess_returns: tuple[float, ...],
    oos_total_returns: tuple[float | None, ...],
    oos_excess_returns: tuple[float | None, ...],
    max_drawdowns: tuple[float, ...],
    trade_counts: tuple[int, ...],
    oos_trade_counts: tuple[int | None, ...] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, snapshot_id in enumerate(snapshot_ids):
        rows.append(
            {
                "run_id": f"run-{fast_period}-{slow_period}-{leverage}-{index}",
                "dataset_snapshot_id": snapshot_id,
                "timeframe": "1h",
                "fast_period": fast_period,
                "slow_period": slow_period,
                "leverage": leverage,
                "total_return": total_returns[index],
                "excess_return": excess_returns[index],
                "oos_total_return": oos_total_returns[index],
                "oos_excess_return": oos_excess_returns[index],
                "max_drawdown": max_drawdowns[index],
                "trade_count": trade_counts[index],
                "oos_trade_count": (oos_trade_counts[index] if oos_trade_counts is not None else trade_counts[index]),
            }
        )
    return rows
