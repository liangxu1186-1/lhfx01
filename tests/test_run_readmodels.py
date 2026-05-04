from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_backtest_workbench.app.readmodels import (
    build_equity_chart_rows,
    build_multi_run_equity_rows,
    build_run_comparison_views,
    build_trade_explorer_rows,
    build_trade_rows,
    build_warning_rows,
    build_parameter_research_workspace,
    load_research_candidate_trade_attribution,
    TradeFilter,
    filter_trade_rows,
    filter_run_summary_views,
    json_ready,
    list_run_summary_views,
    load_run_detail_view,
)
from crypto_backtest_workbench.app.readmodels.runs import _parameter_summary
from crypto_backtest_workbench.domain.models import (
    CanonicalCandle,
    MarketType,
    Side,
    SignalAction,
    SignalIntent,
    ValidationSplit,
    ValidationTargetType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import SingleRunOrchestrator, SingleRunRequest
from crypto_backtest_workbench.storage.repositories import FileRunRepository


def test_run_readmodels_build_summary_and_detail(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))

    summaries = list_run_summary_views(repository)

    assert [summary.run_id for summary in summaries] == ["run-002", "run-001"]
    assert summaries[0].strategy_name == "manual-signals"
    assert summaries[0].trade_count == 1
    assert summaries[0].benchmark_return is not None
    assert summaries[0].fast_period == 2
    assert summaries[0].slow_period == 5
    assert summaries[0].leverage == 2.0
    assert summaries[0].max_drawdown >= 0
    assert summaries[0].is_total_return is not None
    assert summaries[0].oos_total_return is not None

    detail = load_run_detail_view(repository, "run-001")
    equity_rows = build_equity_chart_rows(detail)
    trade_rows = build_trade_rows(detail)
    warning_rows = build_warning_rows(detail)

    assert detail.run.run_id == "run-001"
    assert detail.validation_summary is not None
    assert len(equity_rows) == len(detail.execution.equity_curve)
    assert equity_rows[0]["strategy_equity"] == detail.execution.equity_curve[0].equity
    assert equity_rows[0]["benchmark_equity"] is not None
    assert trade_rows[0]["trade_id"] == detail.execution.trades[0].trade_id
    assert len(warning_rows) == len(detail.execution.warnings)


def test_run_readmodels_filter_summary_views(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="alpha-002"))

    summaries = list_run_summary_views(repository)
    filtered = filter_run_summary_views(
        summaries,
        strategy_names={"manual-signals"},
        statuses={"success"},
        dataset_query="alpha",
    )

    assert [summary.run_id for summary in filtered] == ["alpha-002"]


def test_run_readmodels_build_comparison_views_and_multi_run_equity(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))

    details = [
        load_run_detail_view(repository, "run-001"),
        load_run_detail_view(repository, "run-002"),
    ]

    comparison_views = build_run_comparison_views(details)
    equity_rows = build_multi_run_equity_rows(details)

    assert [row.run_id for row in comparison_views] == ["run-001", "run-002"]
    assert comparison_views[0].excess_return is not None
    assert f"{details[0].run.run_id}_equity" in equity_rows[0]
    assert f"{details[1].run.run_id}_equity" in equity_rows[0]


def test_json_ready_converts_non_finite_numbers_to_null() -> None:
    assert json_ready({"nan": float("nan"), "inf": float("inf"), "negative_inf": float("-inf")}) == {
        "nan": None,
        "inf": None,
        "negative_inf": None,
    }


def test_run_readmodels_build_trade_explorer_rows(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))

    details = [
        load_run_detail_view(repository, "run-001"),
        load_run_detail_view(repository, "run-002"),
    ]
    rows = build_trade_explorer_rows(details)

    assert len(rows) == 2
    assert rows[0]["run_id"] == "run-001"
    assert rows[1]["run_id"] == "run-002"
    assert rows[0]["strategy_name"] == "manual-signals"


def test_run_readmodels_filter_trade_rows(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))

    details = [
        load_run_detail_view(repository, "run-001"),
        load_run_detail_view(repository, "run-002"),
    ]
    trade_rows = build_trade_explorer_rows(details)

    filtered = filter_trade_rows(
        trade_rows,
        trade_filter=TradeFilter(
            run_ids=("run-002",),
            outcome="winner",
            sides=("long",),
            min_holding_bars=0,
            max_holding_bars=10,
            reason_query="open-long",
        ),
    )

    assert len(filtered) == 1
    assert filtered[0]["run_id"] == "run-002"
    assert filtered[0]["side"] == "long"


def test_trade_attribution_builds_candidate_buckets_and_checks(tmp_path) -> None:
    repository = FileRunRepository(tmp_path)
    repository.save_single_run_result(_build_single_run_result(run_id="run-001"))
    repository.save_single_run_result(_build_single_run_result(run_id="run-002"))
    workspace = build_parameter_research_workspace(repository)
    candidate_id = workspace.parameter_groups[0].group_key

    attribution = load_research_candidate_trade_attribution(repository, candidate_id=candidate_id).as_dict()

    assert attribution["candidate_id"] == candidate_id
    assert attribution["summary"]["run_count"] == 2
    assert attribution["summary"]["trade_count"] == 2
    assert attribution["summary"]["feature_meta_coverage"] == 1.0
    assert any(bucket["dimension"] == "side" for bucket in attribution["buckets"])
    assert any(check["key"] == "total_trade_sample" for check in attribution["anti_overfit_checks"])


def _build_single_run_result(*, run_id: str):
    candles = _build_candles([100.0, 102.0, 105.0, 103.0, 104.0])
    signals = [
        SignalIntent(
            signal_id=f"{run_id}-signal-open",
            run_id=run_id,
            timestamp=candles[0].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.OPEN,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="open-long",
            meta_json={
                "feature_values": {
                    "trend_fast_ema": 101.0,
                    "trend_slow_ema": 99.0,
                    "entry_ema": 100.0,
                    "atr": 2.0,
                    "low": 99.0,
                    "close": 100.0,
                    "previous_high": 99.5,
                },
                "risk_spec": {
                    "stop_loss_mode": "atr_multiple",
                    "stop_loss_value": 1.5,
                    "take_profit_mode": "rr",
                    "take_profit_value": 2.0,
                    "atr_value": 2.0,
                    "min_stop_pct": 0.003,
                },
            },
        ),
        SignalIntent(
            signal_id=f"{run_id}-signal-close",
            run_id=run_id,
            timestamp=candles[2].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-long",
        ),
        SignalIntent(
            signal_id=f"{run_id}-signal-warning",
            run_id=run_id,
            timestamp=candles[-1].timestamp,
            symbol="BTC/USDT:USDT",
            action=SignalAction.CLOSE,
            side=Side.LONG,
            qty_policy_ref="fixed_1",
            reason_code="close-no-next-open",
        ),
    ]
    return SingleRunOrchestrator().execute(
        request=SingleRunRequest(
            run_id=run_id,
            strategy_name="manual-signals",
            strategy_version="strategy-v1",
            dataset_snapshot_id="snapshot-001",
            feature_artifact_id="feature-001",
            validation_split_id="split-001",
            execution_policy_id="signal_on_bar_close_fill_on_next_bar_open",
            metric_policy_id="metric-v1",
            engine_version="engine-v1",
            fee_model_version="fee-v1",
            slippage_model_version="slippage-v1",
            fee_model_params_json={"rate": 0.001},
            slippage_model_params_json={"bps": 0},
            benchmark_config_json={"benchmark_type": "buy_and_hold"},
            resolved_config_json={
                "strategy_params": {
                    "fast_period": 2,
                    "slow_period": 5,
                    "qty_policy_ref": "fixed_1",
                },
                "execution_constraints": {
                    "leverage": 2.0,
                },
            },
            resolved_config_uri="memory://resolved-config.json",
            benchmark_config_uri="memory://benchmark-config.json",
            run_manifest_uri="memory://run-manifest.json",
            seed=7,
        ),
        candles=candles,
        signals=signals,
        constraints=ExecutionConstraints(
            initial_cash=1_000.0,
            leverage=2.0,
            fee_rate=0.001,
            qty_by_policy={"fixed_1": 1.0},
        ),
        validation_split=ValidationSplit(
            validation_split_id="split-001",
            target_type=ValidationTargetType.DATASET_SNAPSHOT,
            target_id="snapshot-001",
            warmup_bars=0,
            is_start=candles[0].timestamp,
            is_end=candles[4].timestamp,
            oos_start=candles[4].timestamp,
            oos_end=candles[4].timestamp + timedelta(hours=1),
        ),
    )


def _build_candles(close_prices: list[float]) -> list[CanonicalCandle]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[CanonicalCandle] = []
    for index, close_price in enumerate(close_prices):
        timestamp = start + timedelta(hours=index)
        candles.append(
            CanonicalCandle(
                timestamp=timestamp,
                symbol="BTC/USDT:USDT",
                exchange="binance",
                market_type=MarketType.LINEAR_USDT_PERPETUAL,
                timeframe="1h",
                open=close_price,
                high=close_price + 1,
                low=close_price - 1,
                close=close_price,
                volume=100.0,
            )
        )
    return candles


def test_run_summary_parameter_summary_includes_risk_sizing() -> None:
    summary = _parameter_summary(
        "ema_pullback_atr_v2",
        {
            "trend_fast_period": 8,
            "trend_slow_period": 34,
            "entry_ema_period": 21,
            "atr_period": 14,
            "atr_entry_tolerance": 0.5,
            "atr_stop_mult": 1.5,
            "risk_reward_ratio": 2.0,
            "qty_policy_ref": "risk_pct_of_equity",
        },
        {
            "leverage": 2.0,
            "risk_pct_per_trade_by_policy": {"risk_pct_of_equity": 0.01},
        },
    )

    assert summary == "tf8 ts34 ema21 atr14 tol0.5 sl1.5 rr2 risk1% l2"
