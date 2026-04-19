"""Minimal read-only Streamlit page for Phase 1 run results."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from crypto_backtest_workbench.app.workflows import (
    RunBacktestWorkflowRequest,
    ingest_dataset_workflow,
    run_backtest_task_workflow,
)
from crypto_backtest_workbench.app.readmodels import (
    build_parameter_lab_rows,
    build_parameter_sensitivity_rows,
    build_equity_chart_rows,
    build_multi_run_equity_rows,
    build_run_comparison_views,
    build_trade_explorer_rows,
    build_trade_rows,
    build_warning_rows,
    ParameterLabFilter,
    TradeFilter,
    filter_parameter_lab_rows,
    filter_trade_rows,
    filter_run_summary_views,
    list_run_summary_views,
    load_run_detail_view,
    parameter_metric_value,
)
from crypto_backtest_workbench.domain.models import (
    DatasetSnapshot,
    MarketType,
    PriceType,
)
from crypto_backtest_workbench.engine.execution import ExecutionConstraints
from crypto_backtest_workbench.jobs import LocalTaskRunner
from crypto_backtest_workbench.storage.repositories import FileRunRepository
from crypto_backtest_workbench.storage.repositories import (
    FileDatasetRepository,
    FileFeatureRepository,
)


def main() -> None:
    st.set_page_config(page_title="加密回测工作台", layout="wide")
    _apply_page_chrome()

    args = _parse_args(sys.argv[1:])
    data_dir = _resolve_data_dir(repository_root=args.repository_root, data_dir=args.data_dir)
    repository_root = Path(args.repository_root)
    repository = FileRunRepository(data_dir)
    summaries = list_run_summary_views(repository)

    _render_page_header(data_dir=data_dir)
    execution_tab, overview_tab, analysis_tab, parameter_tab = st.tabs(
        ["执行台", "运行总览", "单次分析", "参数实验"]
    )

    with execution_tab:
        _render_execution_console(repository_root=repository_root, data_dir=data_dir)

    if not summaries:
        empty_message = "当前还没有已落盘的回测结果。先在“执行台”里导入历史数据并运行第一组回测。"
        with overview_tab:
            st.info(empty_message)
        with analysis_tab:
            st.info(empty_message)
        with parameter_tab:
            st.info(empty_message)
        return

    with overview_tab:
        filtered_summaries = _render_dashboard_filters(summaries)
        if not filtered_summaries:
            st.warning("当前筛选条件下没有匹配的 run。")
        else:
            _render_summary_cards(filtered_summaries)
            _render_summary_table(filtered_summaries)
            compare_ids = _render_run_compare_picker(
                summaries=filtered_summaries,
                key_prefix="overview",
                title="总览对比",
                body="先在筛选后的 run 里圈出几组候选，再做收益、超额收益和资金曲线对比。",
            )
            _render_comparison_section(repository, compare_ids)

    with analysis_tab:
        selected_run_id, selected_compare_ids = _render_run_inspector_controls(
            summaries=summaries,
            total_run_count=len(summaries),
        )
        detail = load_run_detail_view(repository, selected_run_id)
        selected_compare_details = [
            load_run_detail_view(repository, run_id)
            for run_id in list(dict.fromkeys(selected_compare_ids))
        ]

        with st.expander("查看当前运行上下文", expanded=False):
            _render_run_inspector(detail)
        _render_detail_tabs(detail)
        if len(selected_compare_details) > 1:
            _render_trade_explorer_section(selected_compare_details)
        else:
            st.caption("当前只选中 1 个 run，下面不再重复显示跨 run 交易浏览。若要比较多组交易，请在上方“加入对比”里再选至少 1 个 run。")

    with parameter_tab:
        _render_parameter_lab_section(repository, summaries)


def _render_dashboard_filters(summaries):
    strategy_options = sorted({summary.strategy_name for summary in summaries})
    status_options = sorted({summary.status for summary in summaries})
    symbol_options = sorted({summary.symbol for summary in summaries if summary.symbol})
    validation_split_options = sorted({summary.validation_split_id for summary in summaries})
    return_bounds = _float_range_bounds([summary.total_return * 100 for summary in summaries])
    trade_bounds = _int_range_bounds([summary.trade_count for summary in summaries])

    _section_header("总览筛选", "先缩小候选 run 集合，再看总览表和资金曲线对比。筛选器只服务这一页，不再全局占据侧边栏。")
    with st.expander("展开筛选器", expanded=True):
        row1 = st.columns(4)
        selected_strategies = set(
            row1[0].multiselect(
                "策略",
                options=strategy_options,
                default=strategy_options,
                format_func=_strategy_label,
            )
        )
        selected_statuses = set(
            row1[1].multiselect(
                "状态",
                options=status_options,
                default=status_options,
                format_func=_status_label,
            )
        )
        selected_symbols = set(
            row1[2].multiselect(
                "标的",
                options=symbol_options,
                default=symbol_options,
            )
        )
        selected_validation_splits = set(
            row1[3].multiselect(
                "样本切分",
                options=validation_split_options,
                default=validation_split_options,
            )
        )

        row2 = st.columns([1.2, 0.9, 1.1, 1.1])
        dataset_query = row2[0].text_input("Run / 数据集 模糊搜索")
        benchmark_mode = row2[1].selectbox(
            "基准结果",
            options=["all", "with", "without"],
            format_func=_benchmark_mode_label,
        )
        sort_mode = row2[2].selectbox(
            "排序",
            options=["created_at_desc", "total_return_desc", "trade_count_desc", "warning_count_desc"],
            format_func=_sort_mode_label,
        )
        row2[3].caption("当前页只负责筛选与比较，不显示单条 run 的细节。")

        row3 = st.columns(2)
        with row3[0]:
            return_range = _inline_float_slider(
                "收益率范围 (%)",
                bounds=return_bounds,
                key="dashboard_return_range",
            )
        with row3[1]:
            trade_range = _inline_int_slider(
                "交易数范围",
                bounds=trade_bounds,
                key="dashboard_trade_range",
            )

    filtered = filter_run_summary_views(
        summaries,
        strategy_names=selected_strategies or None,
        statuses=selected_statuses or None,
        symbols=selected_symbols or None,
        validation_split_ids=selected_validation_splits or None,
        dataset_query=dataset_query or None,
        min_total_return=return_range[0] / 100,
        max_total_return=return_range[1] / 100,
        min_trade_count=trade_range[0],
        max_trade_count=trade_range[1],
        benchmark_mode=benchmark_mode,
    )
    return _sort_run_summaries(filtered, sort_mode=sort_mode)


def _render_run_compare_picker(*, summaries, key_prefix: str, title: str, body: str) -> list[str]:
    _section_header(title, body)
    run_ids = [summary.run_id for summary in summaries]
    default_ids = run_ids[: min(3, len(run_ids))]
    selected_compare_ids = st.multiselect(
        "选择要对比的 run",
        options=run_ids,
        default=default_ids,
        key=f"{key_prefix}_compare_ids",
        format_func=lambda run_id: _run_option_label(
            next(summary for summary in summaries if summary.run_id == run_id)
        ),
    )
    if not selected_compare_ids and run_ids:
        return [run_ids[0]]
    return list(selected_compare_ids)


def _render_summary_cards(filtered_summaries) -> None:
    returns = [summary.total_return for summary in filtered_summaries]
    trade_counts = [summary.trade_count for summary in filtered_summaries]
    warning_counts = [summary.warning_count for summary in filtered_summaries]
    excess_returns = [summary.excess_return for summary in filtered_summaries if summary.excess_return is not None]
    best_return = max(returns)
    avg_return = sum(returns) / len(returns)
    avg_trades = sum(trade_counts) / len(trade_counts)
    avg_warning_count = sum(warning_counts) / len(warning_counts)

    cols = st.columns(4, gap="large")
    _render_stat_block(cols[0], "筛选后 Run 数", str(len(filtered_summaries)))
    _render_stat_block(cols[1], "最佳收益率", f"{best_return:.2%}")
    if excess_returns:
        _render_stat_block(cols[2], "平均超额收益", f"{(sum(excess_returns) / len(excess_returns)):.2%}")
    else:
        _render_stat_block(cols[2], "平均收益率", f"{avg_return:.2%}")
    _render_stat_block(cols[3], "平均交易 / 告警", f"{avg_trades:.1f} / {avg_warning_count:.1f}")


def _render_summary_table(filtered_summaries) -> None:
    raw_rows = [summary.as_dict() for summary in filtered_summaries]
    page_rows, page_number, page_count, total_rows = _paginate_rows(
        raw_rows,
        key_prefix="summary_table",
        page_size=20,
    )
    summary_df = pd.DataFrame(page_rows)
    if not summary_df.empty:
        summary_df["strategy_name"] = summary_df["strategy_name"].map(_strategy_label)
        summary_df["created_at"] = pd.to_datetime(summary_df["created_at"], utc=True)
        summary_df["status"] = summary_df["status"].map(_status_label)
        summary_df["total_return"] = summary_df["total_return"].map(_format_pct)
        summary_df["win_rate"] = summary_df["win_rate"].map(_format_pct)
        summary_df["profit_factor"] = summary_df["profit_factor"].map(_format_number_or_dash)
        summary_df["benchmark_return"] = summary_df["benchmark_return"].map(_format_pct_or_dash)
        summary_df["excess_return"] = summary_df["excess_return"].map(_format_pct_or_dash)
        summary_df["final_equity"] = summary_df["final_equity"].map(_format_number)
        summary_df = summary_df.rename(columns=_summary_column_labels())
    _section_header("运行总览", "筛选后的运行结果列表。先看收益、状态和交易数，再决定下钻哪组 run。")
    visible_columns = _render_summary_column_picker(summary_df.columns.tolist())
    summary_df = summary_df[visible_columns]
    st.dataframe(summary_df, hide_index=True, use_container_width=True)
    _render_table_pager(
        key_prefix="summary_table",
        page_number=page_number,
        page_count=page_count,
        total_rows=total_rows,
    )


def _render_run_inspector_controls(*, summaries, total_run_count: int) -> tuple[str, list[str]]:
    _section_header("当前聚焦", "先选一个聚焦 run，再决定要不要拉几个 run 一起比较。图表和详情会按当前选择整行展开。")
    picker_cols = st.columns([1.35, 1.15], gap="large")
    with picker_cols[0]:
        selected_run_id = st.selectbox(
            "聚焦运行",
            options=[summary.run_id for summary in summaries],
            index=0,
            format_func=lambda run_id: _run_option_label(
                next(summary for summary in summaries if summary.run_id == run_id)
            ),
        )
    with picker_cols[1]:
        selected_compare_ids = st.multiselect(
            "加入对比",
            options=[summary.run_id for summary in summaries],
            default=[selected_run_id],
        )
    selected_summary = next(summary for summary in summaries if summary.run_id == selected_run_id)
    st.caption(f"筛选结果 {len(summaries)} / 全部 {total_run_count} 个 run")
    _render_compact_summary_bar(
        [
            ("当前策略", _strategy_label(selected_summary.strategy_name)),
            ("当前状态", _status_label(selected_summary.status)),
            ("当前收益率", _format_pct(selected_summary.total_return)),
            ("当前交易 / 告警", f"{selected_summary.trade_count} / {selected_summary.warning_count}"),
        ]
    )
    if not selected_compare_ids:
        selected_compare_ids = [selected_run_id]
    return selected_run_id, selected_compare_ids


def _render_run_inspector(detail) -> None:
    symbol = str(detail.manifest.resolved_config_json.get("symbol") or "-")
    timeframe = str(detail.manifest.resolved_config_json.get("timeframe") or "-")
    strategy_params = detail.manifest.resolved_config_json.get("strategy_params") or {}
    strategy_display_name = _strategy_label(
        detail.run.strategy_name,
        fast_period=_int_or_none(strategy_params.get("fast_period")),
        slow_period=_int_or_none(strategy_params.get("slow_period")),
    )
    execution_constraints = detail.manifest.resolved_config_json.get("execution_constraints") or {}
    benchmark_return = None
    excess_return = None
    if detail.benchmark is not None:
        benchmark_return = detail.benchmark.result.return_pct
        excess_return = detail.metrics.total_return - benchmark_return
    _section_header("运行检查器", "查看当前 run 的身份、数据来源和最重要的运行指标。这里是快速判断，不替代下方的详细标签页。")
    _render_compact_summary_bar(
        [
            ("运行 ID", detail.run.run_id),
            ("策略", strategy_display_name),
            ("标的 / 周期", f"{symbol} · {timeframe}"),
            ("状态", _status_label(detail.run.status.value)),
            ("数据集", detail.run.dataset_snapshot_id),
            ("样本切分", detail.run.validation_split_id),
            ("特征产物", detail.run.feature_artifact_id),
        ],
    )
    _render_compact_summary_bar(
        [
            ("最终权益", _format_number(detail.metrics.final_equity)),
            ("总收益率", _format_pct(detail.metrics.total_return)),
            ("基准 / 超额", f"{_format_pct_or_dash(benchmark_return)} / {_format_pct_or_dash(excess_return)}"),
            ("胜率", _format_pct(detail.metrics.win_rate)),
            ("盈亏比", _format_number_or_dash(detail.metrics.profit_factor)),
            ("订单 / 成交", f"{len(detail.execution.orders)} / {len(detail.execution.fills)}"),
            ("交易 / 告警", f"{len(detail.execution.trades)} / {len(detail.execution.warnings)}"),
        ],
        compact=True,
    )
    with st.expander("参数快照", expanded=False):
        st.json(
            {
                "strategy_params": _json_ready(strategy_params),
                "execution_constraints": _json_ready(execution_constraints),
            }
        )
    if detail.run.failure_message:
        st.error(detail.run.failure_message)


def _render_comparison_section(repository: FileRunRepository, selected_compare_ids: list[str]) -> None:
    compare_ids = list(dict.fromkeys(selected_compare_ids))
    if len(compare_ids) < 2:
        st.caption("当前总览对比少于 2 个 run，已跳过重复的资金曲线对比。先多选几组 run 再比较。")
        return

    details = [load_run_detail_view(repository, run_id) for run_id in compare_ids]
    comparison_df = pd.DataFrame(
        [row.as_dict() for row in build_run_comparison_views(details)]
    )
    comparison_df["strategy_name"] = comparison_df["strategy_name"].map(_strategy_label)
    comparison_df["total_return"] = comparison_df["total_return"].map(_format_pct)
    comparison_df["benchmark_return"] = comparison_df["benchmark_return"].map(_format_pct_or_dash)
    comparison_df["excess_return"] = comparison_df["excess_return"].map(_format_pct_or_dash)
    comparison_df["final_equity"] = comparison_df["final_equity"].map(_format_number)
    comparison_df["win_rate"] = comparison_df["win_rate"].map(_format_pct)
    comparison_df["profit_factor"] = comparison_df["profit_factor"].map(_format_number_or_dash)
    comparison_df = comparison_df.rename(columns=_comparison_column_labels())
    _section_header("运行对比", "把多组 run 放在同一张表和同一条资金曲线上比较，先看总收益、超额收益和胜率。")
    st.dataframe(comparison_df, hide_index=True, use_container_width=True)

    equity_compare_rows = build_multi_run_equity_rows(details)
    if not equity_compare_rows:
        return

    equity_compare_df = pd.DataFrame(equity_compare_rows)
    equity_compare_df["timestamp"] = pd.to_datetime(equity_compare_df["timestamp"], utc=True)
    equity_compare_df = equity_compare_df.set_index("timestamp")
    numeric_columns = [column for column in equity_compare_df.columns if column.endswith("_equity")]
    if numeric_columns:
        equity_compare_df = equity_compare_df.rename(
            columns={
                f"{detail.run.run_id}_equity": _comparison_series_label(detail)
                for detail in details
            }
        )
        chart_columns = [_comparison_series_label(detail) for detail in details]
        chart_df, original_count = _downsample_chart_frame(equity_compare_df[chart_columns], max_points=720)
        if original_count > len(chart_df):
            st.caption(f"对比曲线已从 {original_count} 个点抽样到 {len(chart_df)} 个点，以减少页面卡顿。")
        _render_timeseries_chart(chart_df, title="多运行资金曲线对比")


def _render_trade_explorer_section(details) -> None:
    _section_header("交易浏览", "把交易视为研究样本。按结果、方向、持仓周期和原因筛，快速找到模式和噪声。")
    trade_rows = build_trade_explorer_rows(details)
    if not trade_rows:
        st.info("当前选择范围内没有交易记录。")
        return

    explorer_filter = _render_trade_explorer_filters(trade_rows)
    filtered_rows = filter_trade_rows(trade_rows, trade_filter=explorer_filter)
    if not filtered_rows:
        st.warning("当前交易筛选条件下没有匹配的交易。")
        return

    cols = st.columns(4)
    net_pnls = [float(row["net_pnl"]) for row in filtered_rows]
    _render_stat_block(cols[0], "交易数", str(len(filtered_rows)))
    _render_stat_block(cols[1], "胜率", f"{(sum(1 for pnl in net_pnls if pnl > 0) / len(net_pnls)):.2%}")
    _render_stat_block(cols[2], "净利润合计", _format_number(sum(net_pnls), digits=4))
    _render_stat_block(cols[3], "平均持仓 K 线数", f"{(sum(int(row['holding_bars']) for row in filtered_rows) / len(filtered_rows)):.1f}")

    page_rows, page_number, page_count, total_rows = _paginate_rows(
        filtered_rows,
        key_prefix="trade_explorer",
        page_size=50,
    )
    trade_df = pd.DataFrame(page_rows)
    trade_df["strategy_name"] = trade_df["strategy_name"].map(_strategy_label)
    trade_df["side"] = trade_df["side"].map(_side_label)
    trade_df["gross_pnl"] = trade_df["gross_pnl"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["fee"] = trade_df["fee"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["net_pnl"] = trade_df["net_pnl"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["return_pct"] = trade_df["return_pct"].map(lambda value: _format_pct(float(value)))
    trade_df = trade_df.rename(columns=_trade_column_labels())
    st.dataframe(trade_df, hide_index=True, use_container_width=True)
    _render_table_pager(
        key_prefix="trade_explorer",
        page_number=page_number,
        page_count=page_count,
        total_rows=total_rows,
    )


def _render_trade_explorer_filters(trade_rows: list[dict[str, object]]) -> TradeFilter:
    run_options = list(dict.fromkeys(str(row["run_id"]) for row in trade_rows))
    side_options = sorted({str(row["side"]) for row in trade_rows})
    max_holding = max(int(row["holding_bars"]) for row in trade_rows)

    with st.expander("交易筛选", expanded=False):
        selected_run_ids = tuple(
            st.multiselect(
                "运行范围",
                options=run_options,
                default=run_options,
                key="trade_explorer_run_ids",
            )
        )
        outcome = st.selectbox(
            "结果",
            options=["all", "winner", "loser", "flat"],
            index=0,
            key="trade_explorer_outcome",
            format_func=_trade_outcome_label,
        )
        selected_sides = tuple(
            st.multiselect(
                "方向",
                options=side_options,
                default=side_options,
                key="trade_explorer_sides",
                format_func=_side_label,
            )
        )
        if max_holding == 0:
            st.caption("持仓 K 线数：当前结果里全部为 0")
            holding_range = (0, 0)
        else:
            holding_range = st.slider(
                "持仓 K 线数",
                min_value=0,
                max_value=max_holding,
                value=(0, max_holding),
                key="trade_explorer_holding_range",
            )
        reason_query = st.text_input(
            "原因关键词",
            key="trade_explorer_reason_query",
        )

    return TradeFilter(
        run_ids=selected_run_ids,
        outcome=outcome,
        sides=selected_sides,
        min_holding_bars=int(holding_range[0]),
        max_holding_bars=int(holding_range[1]),
        reason_query=reason_query or None,
    )


def _render_execution_console(*, repository_root: Path, data_dir: Path) -> None:
    _section_header("执行面板", "这里可以直接从页面发起数据导入和单次回测。页面负责提交，底层仍然走现有 workflow 和本地任务执行。")
    ingest_tab, run_tab = st.tabs(["导入历史数据", "运行双 EMA 交叉回测"])
    with ingest_tab:
        _render_ingest_form(repository_root=repository_root, data_dir=data_dir)
    with run_tab:
        _render_run_form(data_dir=data_dir)


def _render_ingest_form(*, repository_root: Path, data_dir: Path) -> None:
    with st.form("cbw_ingest_form", clear_on_submit=False):
        cols = st.columns(4)
        exchange = cols[0].text_input("交易所", value="binanceusdm")
        symbol = cols[1].text_input("交易对", value="BTC/USDT:USDT")
        timeframe = cols[2].selectbox(
            "周期",
            options=["1d", "4h", "1h", "15m"],
            index=2,
            format_func=_timeframe_label,
        )
        limit = cols[3].number_input("单次拉取上限", min_value=50, value=1000, step=50)

        time_cols = st.columns(2)
        since_text = time_cols[0].text_input("开始时间 (ISO8601)", value="2024-01-01T00:00:00+00:00")
        until_text = time_cols[1].text_input("结束时间 (ISO8601，可选)", value="")
        with st.expander("高级导入选项", expanded=False):
            extra_cols = st.columns(4)
            market_type = extra_cols[0].selectbox(
                "市场类型",
                options=[MarketType.LINEAR_USDT_PERPETUAL.value],
                format_func=_market_type_label,
            )
            price_type = extra_cols[1].selectbox(
                "价格类型",
                options=[PriceType.LAST.value],
                format_func=_price_type_label,
            )
            exchange_options_json = extra_cols[2].text_input("交易所选项 JSON", value='{"options":{"defaultType":"future"}}')
            extra_params_json = extra_cols[3].text_input("附加参数 JSON", value="")
            keep_open_last_candle = st.checkbox("保留最后一根未闭合 K 线", value=False)
        submitted = st.form_submit_button("开始导入", use_container_width=True)

    if not submitted:
        return

    try:
        since = _parse_iso_datetime_input(since_text)
        until = _parse_iso_datetime_input(until_text) if until_text.strip() else None
        exchange_options = _parse_json_input(exchange_options_json, field_name="交易所选项 JSON")
        extra_params = _parse_json_input(extra_params_json, field_name="附加参数 JSON")
        with st.spinner("正在拉取历史数据并写入本地数据集..."):
            result = ingest_dataset_workflow(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                until=until,
                market_type=MarketType(market_type),
                price_type=PriceType(price_type),
                repository_root=repository_root,
                data_dir=data_dir,
                limit=int(limit),
                drop_unclosed_last_candle=not keep_open_last_candle,
                extra_params=extra_params,
                exchange_options=exchange_options,
            )
    except Exception as exc:
        st.error(f"导入失败：{exc}")
        return

    st.success(
        f"导入完成：{result.snapshot.dataset_snapshot_id}，共 {result.snapshot.row_count} 根 K 线。"
    )
    st.caption(f"快照路径：{result.snapshot_path}")
    st.rerun()


def _render_run_form(*, data_dir: Path) -> None:
    snapshots = _load_dataset_snapshots(data_dir)
    if not snapshots:
        st.info("当前还没有可用数据集。先在上一个标签页导入一组历史数据。")
        return

    snapshot_ids = [snapshot.dataset_snapshot_id for snapshot in snapshots]
    snapshot_by_id = {snapshot.dataset_snapshot_id: snapshot for snapshot in snapshots}
    default_snapshot = snapshot_ids[0]

    with st.form("cbw_run_form", clear_on_submit=False):
        snapshot_id = st.selectbox(
            "数据集快照",
            options=snapshot_ids,
            format_func=lambda value: _snapshot_option_label(snapshot_by_id[value]),
        )
        selected_snapshot = snapshot_by_id[snapshot_id]

        meta_cols = st.columns(3)
        run_id = meta_cols[0].text_input("运行 ID", value=_default_run_id(selected_snapshot))
        benchmark_enabled = meta_cols[1].checkbox("启用买入持有基准", value=True)
        qty_policy_ref = meta_cols[2].text_input("下单数量策略", value="fixed_notional_v1")

        param_cols = st.columns(4)
        fast_period = param_cols[0].number_input("快线周期", min_value=1, value=12, step=1)
        slow_period = param_cols[1].number_input("慢线周期", min_value=2, value=26, step=1)
        qty = param_cols[2].number_input("数量", min_value=0.00000001, value=0.01, step=0.01, format="%.8f")
        initial_cash = param_cols[3].number_input("初始资金", min_value=1.0, value=10000.0, step=100.0)
        with st.expander("执行约束", expanded=False):
            execution_cols = st.columns(4)
            leverage = execution_cols[0].number_input("杠杆", min_value=1.0, value=1.0, step=1.0)
            fee_rate = execution_cols[1].number_input("手续费率", min_value=0.0, value=0.0004, step=0.0001, format="%.6f")
            slippage_bps = execution_cols[2].number_input("滑点 (bps)", min_value=0.0, value=0.0, step=1.0)
            min_notional = execution_cols[3].number_input("最小名义金额", min_value=0.0, value=0.0, step=10.0)

        submitted = st.form_submit_button("运行回测", use_container_width=True)

    if not submitted:
        return

    dataset_repository = FileDatasetRepository(data_dir)
    feature_repository = FileFeatureRepository(data_dir)
    run_repository = FileRunRepository(data_dir)
    runner = LocalTaskRunner()
    try:
        with st.spinner("正在计算特征、生成信号并执行回测..."):
            task_result = run_backtest_task_workflow(
                runner=runner,
                dataset_repository=dataset_repository,
                feature_repository=feature_repository,
                run_repository=run_repository,
                request=RunBacktestWorkflowRequest(
                    run_id=run_id,
                    snapshot=selected_snapshot,
                    strategy_params={
                        "fast_period": int(fast_period),
                        "slow_period": int(slow_period),
                        "qty_policy_ref": qty_policy_ref,
                    },
                    constraints=ExecutionConstraints(
                        initial_cash=float(initial_cash),
                        leverage=float(leverage),
                        fee_rate=float(fee_rate),
                        slippage_bps=float(slippage_bps),
                        min_notional=float(min_notional),
                        qty_by_policy={qty_policy_ref: float(qty)},
                    ),
                    enable_buy_and_hold_benchmark=benchmark_enabled,
                ),
            )
    except Exception as exc:
        st.error(f"回测失败：{exc}")
        return

    if task_result.output is None:
        st.error(
            f"任务失败：{task_result.task.failure_code.value if task_result.task.failure_code else 'UNKNOWN'} / "
            f"{task_result.task.failure_stage or '-'} / {task_result.task.failure_message or '-'}"
        )
        return

    output = task_result.output.workflow_result
    st.success(
        f"回测完成：{output.single_run_result.run.run_id}，收益率 {_format_pct(output.single_run_result.metrics.total_return)}，"
        f"交易数 {output.single_run_result.metrics.trade_count}。"
    )
    st.caption(f"特征产物：{output.feature_artifact.feature_artifact_id}")
    st.rerun()


def _render_parameter_lab_section(repository: FileRunRepository, filtered_summaries) -> None:
    _section_header("参数实验台", "这是 Phase 1 的只读参数视图。它不提交新实验，只汇总已跑过的参数组合，帮助你判断哪些区间值得继续研究。")
    candidate_run_ids = [summary.run_id for summary in filtered_summaries]
    parameter_rows = build_parameter_lab_rows(repository, run_ids=candidate_run_ids)
    if not parameter_rows:
        st.info("当前筛选范围内没有可用于参数分析的 run。")
        return

    parameter_filter, metric_name, sensitivity_parameter = _render_parameter_lab_filters(parameter_rows)
    filtered_rows = filter_parameter_lab_rows(parameter_rows, parameter_filter=parameter_filter)
    if not filtered_rows:
        st.warning("当前参数筛选条件下没有匹配的参数组合。")
        return

    metric_values = [parameter_metric_value(row, metric_name) for row in filtered_rows]
    metric_values = [value for value in metric_values if value is not None]
    unique_fast = len({row.fast_period for row in filtered_rows if row.fast_period is not None})
    unique_slow = len({row.slow_period for row in filtered_rows if row.slow_period is not None})
    unique_combinations = len(
        {
            (row.fast_period, row.slow_period, row.qty_policy_ref, row.validation_split_id)
            for row in filtered_rows
        }
    )

    cols = st.columns(4)
    _render_stat_block(cols[0], "参数组合数", str(unique_combinations))
    _render_stat_block(cols[1], "快线 / 慢线取值", f"{unique_fast} / {unique_slow}")
    _render_stat_block(cols[2], "当前指标最佳值", _format_metric_value(max(metric_values), metric_name) if metric_values else "-")
    _render_stat_block(cols[3], "当前指标均值", _format_metric_value(sum(metric_values) / len(metric_values), metric_name) if metric_values else "-")

    parameter_raw_rows = [row.as_dict() for row in filtered_rows]
    page_rows, page_number, page_count, total_rows = _paginate_rows(
        parameter_raw_rows,
        key_prefix="parameter_lab_table",
        page_size=25,
    )
    parameter_df = pd.DataFrame(page_rows)
    parameter_df["strategy_name"] = parameter_df["strategy_name"].map(_strategy_label)
    parameter_df["qty_policy_ref"] = parameter_df["qty_policy_ref"].map(_qty_policy_label)
    parameter_df["created_at"] = pd.to_datetime(parameter_df["created_at"], utc=True)
    parameter_df["status"] = parameter_df["status"].map(_status_label)
    parameter_df["total_return"] = parameter_df["total_return"].map(_format_pct)
    parameter_df["benchmark_return"] = parameter_df["benchmark_return"].map(_format_pct_or_dash)
    parameter_df["excess_return"] = parameter_df["excess_return"].map(_format_pct_or_dash)
    parameter_df["win_rate"] = parameter_df["win_rate"].map(_format_pct)
    parameter_df["profit_factor"] = parameter_df["profit_factor"].map(_format_number_or_dash)
    parameter_df["final_equity"] = parameter_df["final_equity"].map(_format_number)
    parameter_df["fee_rate"] = parameter_df["fee_rate"].map(_format_number_or_dash)
    parameter_df["slippage_bps"] = parameter_df["slippage_bps"].map(_format_number_or_dash)
    parameter_df["leverage"] = parameter_df["leverage"].map(_format_number_or_dash)
    parameter_df = parameter_df.rename(columns=_parameter_lab_column_labels())
    st.dataframe(parameter_df, hide_index=True, use_container_width=True)
    _render_table_pager(
        key_prefix="parameter_lab_table",
        page_number=page_number,
        page_count=page_count,
        total_rows=total_rows,
    )

    chart_col, sensitivity_col = st.columns([1.2, 1.0], gap="large")
    with chart_col:
        _render_parameter_heatmap(filtered_rows, metric_name=metric_name)
    with sensitivity_col:
        _render_parameter_sensitivity(filtered_rows, parameter_name=sensitivity_parameter, metric_name=metric_name)


def _render_parameter_lab_filters(parameter_rows) -> tuple[ParameterLabFilter, str, str]:
    strategy_options = sorted({row.strategy_name for row in parameter_rows})
    validation_options = sorted({row.validation_split_id for row in parameter_rows})
    fast_bounds = _int_range_bounds([row.fast_period for row in parameter_rows if row.fast_period is not None])
    slow_bounds = _int_range_bounds([row.slow_period for row in parameter_rows if row.slow_period is not None])

    with st.expander("参数筛选", expanded=False):
        selected_strategies = tuple(
            st.multiselect(
                "策略范围",
                options=strategy_options,
                default=strategy_options,
                key="parameter_lab_strategy_names",
                format_func=_strategy_label,
            )
        )
        selected_splits = tuple(
            st.multiselect(
                "样本切分",
                options=validation_options,
                default=validation_options,
                key="parameter_lab_validation_split_ids",
            )
        )
        dataset_query = st.text_input("Run / 数据集 / 标的 模糊搜索", key="parameter_lab_dataset_query")
        benchmark_mode = st.selectbox(
            "基准结果",
            options=["all", "with", "without"],
            key="parameter_lab_benchmark_mode",
            format_func=_benchmark_mode_label,
        )
        fast_range = _inline_int_slider(
            "快线周期",
            bounds=fast_bounds,
            key="parameter_lab_fast_period_range",
        )
        slow_range = _inline_int_slider(
            "慢线周期",
            bounds=slow_bounds,
            key="parameter_lab_slow_period_range",
        )
        metric_name = st.selectbox(
            "分析指标",
            options=["total_return", "excess_return", "win_rate", "trade_count", "profit_factor"],
            key="parameter_lab_metric_name",
            format_func=_metric_label,
        )
        sensitivity_parameter = st.radio(
            "敏感参数",
            options=["fast_period", "slow_period"],
            key="parameter_lab_sensitivity_parameter",
            horizontal=True,
            format_func=_parameter_name_label,
        )

    return (
        ParameterLabFilter(
            strategy_names=selected_strategies,
            validation_split_ids=selected_splits,
            dataset_query=dataset_query or None,
            fast_period_range=fast_range,
            slow_period_range=slow_range,
            benchmark_mode=benchmark_mode,
        ),
        metric_name,
        sensitivity_parameter,
    )


def _render_parameter_heatmap(rows, *, metric_name: str) -> None:
    _section_header("参数热区", "用快线和慢线构成二维参数平面。这里先看高值区是否连续，再决定是否值得扩更多组合。")
    heatmap_source_rows = []
    for row in rows:
        metric_value = parameter_metric_value(row, metric_name)
        if row.fast_period is None or row.slow_period is None or metric_value is None:
            continue
        heatmap_source_rows.append(
            {
                "fast_period": row.fast_period,
                "slow_period": row.slow_period,
                metric_name: metric_value,
            }
        )
    if not heatmap_source_rows:
        st.caption("当前筛选范围内没有足够的快线 / 慢线组合用于热区展示。")
        return

    heatmap_df = pd.DataFrame(heatmap_source_rows).pivot_table(
        index="slow_period",
        columns="fast_period",
        values=metric_name,
        aggfunc="mean",
    )
    heatmap_df = heatmap_df.sort_index().sort_index(axis=1)
    formatted_heatmap_df = heatmap_df.copy()
    for column in formatted_heatmap_df.columns:
        formatted_heatmap_df[column] = formatted_heatmap_df[column].map(
            lambda value: _format_metric_value(value, metric_name) if pd.notna(value) else "-"
        )
    st.dataframe(formatted_heatmap_df, use_container_width=True)


def _render_parameter_sensitivity(rows, *, parameter_name: str, metric_name: str) -> None:
    _section_header("参数敏感性", "把单个参数拉成一维，看平均值和最好值是否稳定，避免只盯住某个尖峰。")
    sensitivity_rows = build_parameter_sensitivity_rows(
        rows,
        parameter_name=parameter_name,
        metric_name=metric_name,
    )
    if not sensitivity_rows:
        st.caption("当前筛选范围内没有足够的参数取值用于敏感性展示。")
        return

    sensitivity_df = pd.DataFrame(sensitivity_rows)
    chart_df = sensitivity_df.set_index(parameter_name)[["avg_metric", "best_metric"]]
    chart_df = chart_df.rename(columns={"avg_metric": "平均值", "best_metric": "最好值"})
    sampled_chart_df, original_count = _downsample_chart_frame(chart_df, max_points=240)
    if original_count > len(sampled_chart_df):
        st.caption(f"参数敏感性曲线已从 {original_count} 个点抽样到 {len(sampled_chart_df)} 个点。")
    _render_metric_chart(sampled_chart_df, title="参数敏感性")

    display_df = sensitivity_df.copy()
    display_df["avg_metric"] = display_df["avg_metric"].map(lambda value: _format_metric_value(value, metric_name))
    display_df["best_metric"] = display_df["best_metric"].map(lambda value: _format_metric_value(value, metric_name))
    display_df = display_df.rename(
        columns={
            parameter_name: _parameter_name_label(parameter_name),
            "run_count": "样本数",
            "avg_metric": "平均值",
            "best_metric": "最好值",
        }
    )
    st.dataframe(display_df, hide_index=True, use_container_width=True)


def _render_detail_tabs(detail) -> None:
    _section_header("聚焦运行工作区", f"当前查看 {detail.run.run_id}。用下方标签页分别看资金曲线、交易明细，以及告警和配置。")
    overview_tab, trades_tab, warnings_tab = st.tabs(["资金曲线", "交易明细", "告警与配置"])
    with overview_tab:
        _render_detail_overview(detail)
    with trades_tab:
        _render_detail_trades(detail)
    with warnings_tab:
        _render_detail_warnings(detail)


def _render_detail_overview(detail) -> None:
    strategy_params = detail.manifest.resolved_config_json.get("strategy_params") or {}
    cols = st.columns(5)
    _render_stat_block(
        cols[0],
        "策略",
        _strategy_label(
            detail.run.strategy_name,
            fast_period=_int_or_none(strategy_params.get("fast_period")),
            slow_period=_int_or_none(strategy_params.get("slow_period")),
        ),
    )
    _render_stat_block(cols[1], "交易数", str(detail.metrics.trade_count))
    _render_stat_block(cols[2], "总收益率", f"{detail.metrics.total_return:.2%}")
    _render_stat_block(cols[3], "最终权益", _format_number(detail.metrics.final_equity))
    benchmark_return = None
    if detail.benchmark is not None:
        benchmark_return = detail.benchmark.result.return_pct
    _render_stat_block(cols[4], "基准收益率", "-" if benchmark_return is None else f"{benchmark_return:.2%}")
    chart_rows = build_equity_chart_rows(detail)
    chart_df = pd.DataFrame(chart_rows)
    _section_header("资金曲线", "策略权益与基准权益放在同一图里，先看趋势是否持续，再看回撤段。")
    if chart_df.empty:
        st.info("当前 run 没有资金曲线数据。")
    else:
        chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], utc=True)
        chart_df = chart_df.set_index("timestamp")
        chart_df = chart_df.rename(
            columns={
                "strategy_equity": "策略权益",
                "benchmark_equity": "基准权益",
            }
        )
        chart_columns = ["策略权益"]
        if "基准权益" in chart_df.columns and chart_df["基准权益"].notna().any():
            chart_columns.append("基准权益")
        line_chart_df, original_count = _downsample_chart_frame(chart_df[chart_columns], max_points=720)
        if original_count > len(line_chart_df):
            st.caption(f"资金曲线已从 {original_count} 个点抽样到 {len(line_chart_df)} 个点，以减少页面卡顿。")
        _render_timeseries_chart(line_chart_df, title="单运行资金曲线")


def _render_detail_trades(detail) -> None:
    _section_header("交易明细", "查看每笔交易的方向、进出场价格、手续费和收益。")
    trade_rows = build_trade_rows(detail)
    if not trade_rows:
        st.info("当前 run 没有已平仓交易。")
    else:
        page_rows, page_number, page_count, total_rows = _paginate_rows(
            trade_rows,
            key_prefix=f"detail_trades_{detail.run.run_id}",
            page_size=50,
        )
        trade_df = pd.DataFrame(page_rows)
        if "strategy_name" in trade_df.columns:
            trade_df["strategy_name"] = trade_df["strategy_name"].map(_strategy_label)
        trade_df["side"] = trade_df["side"].map(_side_label)
        trade_df["gross_pnl"] = trade_df["gross_pnl"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["fee"] = trade_df["fee"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["net_pnl"] = trade_df["net_pnl"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["return_pct"] = trade_df["return_pct"].map(lambda value: _format_pct(float(value)))
        trade_df = trade_df.rename(columns=_trade_column_labels())
        st.dataframe(trade_df, hide_index=True, use_container_width=True)
        _render_table_pager(
            key_prefix=f"detail_trades_{detail.run.run_id}",
            page_number=page_number,
            page_count=page_count,
            total_rows=total_rows,
        )


def _render_detail_warnings(detail) -> None:
    _section_header("告警", "数据、执行和分析阶段的异常或提示统一放在这里看。")
    warning_df = pd.DataFrame(build_warning_rows(detail))
    if warning_df.empty:
        st.caption("当前 run 没有告警。")
    else:
        warning_df["warning_type"] = warning_df["warning_type"].map(_warning_type_label)
        warning_df["severity"] = warning_df["severity"].map(_severity_label)
        warning_df = warning_df.rename(columns=_warning_column_labels())
        st.dataframe(warning_df, hide_index=True, use_container_width=True)

    with st.expander("运行清单 / 配置", expanded=False):
        st.json(
            {
                "manifest": _json_ready(asdict(detail.manifest)),
                "run": _json_ready(asdict(detail.run)),
            }
        )


def _apply_page_chrome() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
        :root {
            --cbw-bg: #f5f7f3;
            --cbw-surface: rgba(255, 255, 255, 0.72);
            --cbw-surface-strong: rgba(255, 255, 255, 0.92);
            --cbw-border: rgba(21, 36, 31, 0.08);
            --cbw-ink: #15241f;
            --cbw-muted: #62756d;
            --cbw-accent: #0d8a72;
            --cbw-accent-soft: rgba(13, 138, 114, 0.08);
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(13, 138, 114, 0.08), transparent 30%),
                radial-gradient(circle at top right, rgba(18, 48, 61, 0.06), transparent 28%),
                linear-gradient(180deg, #f7f8f5 0%, #eef2ec 100%);
        }
        html, body, [class*="css"] {
            font-family: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif;
            color: var(--cbw-ink);
        }
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {display: none;}
        [data-testid="stDecoration"] {display: none;}
        [data-testid="stStatusWidget"] {display: none;}
        [data-testid="stHeaderActionElements"] {display: none;}
        .block-container {
            padding-top: 1.1rem;
            padding-bottom: 2.4rem;
            max-width: 1400px;
        }
        .cbw-hero {
            display: grid;
            grid-template-columns: minmax(0, 1.6fr) auto;
            gap: 1rem 1.25rem;
            align-items: start;
            padding: 1rem 1.15rem;
            border: 1px solid var(--cbw-border);
            background:
                linear-gradient(135deg, rgba(255,255,255,0.96), rgba(246,250,247,0.92));
            border-radius: 20px;
            box-shadow: 0 10px 28px rgba(16, 31, 26, 0.06);
            margin-bottom: 0.8rem;
        }
        .cbw-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.26rem 0.68rem;
            border-radius: 999px;
            background: rgba(13, 138, 114, 0.08);
            color: var(--cbw-accent);
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-weight: 600;
        }
        .cbw-hero-main {
            min-width: 0;
        }
        .cbw-hero h1 {
            margin: 0.45rem 0 0 0;
            font-size: clamp(1.8rem, 3vw, 2.7rem);
            line-height: 1.02;
            letter-spacing: -0.03em;
            font-weight: 700;
        }
        .cbw-hero p {
            margin: 0.35rem 0 0 0;
            max-width: 48rem;
            color: var(--cbw-muted);
            font-size: 0.93rem;
            line-height: 1.45;
        }
        .cbw-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.65rem;
            justify-content: flex-end;
            align-content: flex-start;
        }
        .cbw-chip {
            padding: 0.38rem 0.72rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.78);
            border: 1px solid var(--cbw-border);
            color: var(--cbw-ink);
            font-size: 0.8rem;
            white-space: nowrap;
        }
        @media (max-width: 980px) {
            .cbw-hero {
                grid-template-columns: 1fr;
            }
            .cbw-meta {
                justify-content: flex-start;
            }
        }
        .cbw-section-head {
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }
        .cbw-section-head h3 {
            margin: 0;
            font-size: 1rem;
            letter-spacing: -0.02em;
        }
        .cbw-section-head p {
            margin: 0.2rem 0 0 0;
            color: var(--cbw-muted);
            font-size: 0.86rem;
            line-height: 1.4;
        }
        .cbw-stat {
            padding: 0.1rem 0 0.55rem 0;
            border-top: 1px solid rgba(13, 138, 114, 0.18);
        }
        .cbw-stat-label {
            color: var(--cbw-muted);
            font-size: 0.74rem;
            margin-bottom: 0.18rem;
        }
        .cbw-stat-value {
            font-size: 1.08rem;
            font-weight: 650;
            letter-spacing: -0.02em;
            color: var(--cbw-ink);
        }
        .cbw-inline-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.55rem 0.75rem;
            margin: 0.55rem 0 0.8rem 0;
        }
        .cbw-inline-meta-compact {
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            margin-top: 0.35rem;
        }
        .cbw-inline-item {
            padding: 0.48rem 0.62rem;
            border-radius: 12px;
            background: rgba(255,255,255,0.68);
            border: 1px solid rgba(21, 36, 31, 0.07);
            min-width: 0;
        }
        .cbw-inline-item span {
            display: block;
            color: var(--cbw-muted);
            font-size: 0.72rem;
            line-height: 1.15;
            margin-bottom: 0.16rem;
        }
        .cbw-inline-item strong {
            display: block;
            color: var(--cbw-ink);
            font-size: 0.94rem;
            line-height: 1.25;
            font-weight: 600;
            word-break: break-word;
        }
        .cbw-inspector-list {
            display: grid;
            gap: 0.55rem;
            margin-bottom: 0.8rem;
        }
        .cbw-inspector-list div {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding-bottom: 0.45rem;
            border-bottom: 1px dashed rgba(21, 36, 31, 0.08);
        }
        .cbw-inspector-list span {
            color: var(--cbw-muted);
            font-size: 0.84rem;
        }
        .cbw-inspector-list strong {
            font-weight: 600;
            color: var(--cbw-ink);
            text-align: right;
        }
        [data-testid="stSidebar"] {
            background: rgba(248, 250, 247, 0.9);
            border-right: 1px solid var(--cbw-border);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--cbw-border);
            border-radius: 18px;
            overflow: hidden;
            background: var(--cbw-surface-strong);
        }
        [data-baseweb="tag"] {
            border-radius: 10px !important;
            min-height: 28px !important;
            font-size: 0.82rem !important;
        }
        [data-testid="stMetric"] {
            background: transparent;
            border: none;
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stFormSubmitButton"] > button {
            min-height: 2.1rem !important;
            padding: 0.2rem 0.7rem !important;
            font-size: 0.84rem !important;
            border-radius: 12px !important;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        div[data-baseweb="textarea"] > div {
            border-radius: 14px !important;
        }
        [data-testid="stExpander"] {
            border: 1px solid var(--cbw-border);
            border-radius: 18px;
            background: var(--cbw-surface);
        }
        [data-baseweb="tab-list"] {
            gap: 0.4rem;
        }
        [data-baseweb="tab-border"] {
            display: none !important;
        }
        button[role="tab"] {
            border-radius: 999px !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            background: rgba(255,255,255,0.84) !important;
            border: 1px solid var(--cbw-border) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--data-dir")
    args, _unknown = parser.parse_known_args(argv)
    return args


def _resolve_data_dir(*, repository_root: str | Path, data_dir: str | Path | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    return Path(repository_root) / "data"


def _load_dataset_snapshots(data_dir: Path) -> list[DatasetSnapshot]:
    datasets_dir = data_dir / "datasets"
    if not datasets_dir.exists():
        return []

    snapshots: list[DatasetSnapshot] = []
    for snapshot_path in sorted(datasets_dir.glob("*/snapshot.json")):
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshots.append(
            DatasetSnapshot(
                dataset_snapshot_id=payload["dataset_snapshot_id"],
                source=payload["source"],
                exchange=payload["exchange"],
                market_type=MarketType(payload["market_type"]),
                symbol=payload["symbol"],
                timeframe=payload["timeframe"],
                time_range_start=_parse_iso_datetime_input(payload["time_range_start"]),
                time_range_end=_parse_iso_datetime_input(payload["time_range_end"]),
                row_count=int(payload["row_count"]),
                schema_version=payload["schema_version"],
                feature_version=payload["feature_version"],
                storage_uri=payload["storage_uri"],
                data_source=payload["data_source"],
                price_type=PriceType(payload.get("price_type", PriceType.LAST.value)),
                created_at=_parse_iso_datetime_input(payload["created_at"]),
            )
        )
    return sorted(snapshots, key=lambda snapshot: snapshot.created_at, reverse=True)


def _parse_iso_datetime_input(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_json_input(value: str, *, field_name: str) -> dict[str, object] | None:
    if not value.strip():
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} 必须是 JSON object")
    return parsed


def _snapshot_option_label(snapshot: DatasetSnapshot) -> str:
    return (
        f"{snapshot.dataset_snapshot_id} · {snapshot.symbol} · {snapshot.timeframe} · "
        f"{snapshot.time_range_start.date()} ~ {snapshot.time_range_end.date()}"
    )


def _default_run_id(snapshot: DatasetSnapshot) -> str:
    symbol_token = snapshot.symbol.replace("/", "_").replace(":", "_").lower()
    return f"run-{symbol_token}-{snapshot.timeframe}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _render_page_header(*, data_dir: Path) -> None:
    st.markdown(
        f"""
        <section class="cbw-hero">
          <div class="cbw-hero-main">
            <div class="cbw-kicker">Phase 1 · Research Console</div>
            <h1>加密回测工作台</h1>
            <p>执行、总览、单次分析和参数实验已经拆开，首屏只保留最必要的上下文，不再让头部抢占工作区。</p>
          </div>
          <div class="cbw-meta">
            <div class="cbw-chip">数据目录：{data_dir}</div>
            <div class="cbw-chip">模式：分区执行 + 分区分析</div>
            <div class="cbw-chip">视图：执行台 / 运行总览 / 单次分析 / 参数实验</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _section_header(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="cbw-section-head">
          <h3>{title}</h3>
          <p>{body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_stat_block(container, label: str, value: str) -> None:
    container.markdown(
        f"""
        <div class="cbw-stat">
          <div class="cbw-stat-label">{label}</div>
          <div class="cbw-stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _summary_column_labels() -> dict[str, str]:
    return {
        "run_id": "运行 ID",
        "strategy_name": "策略",
        "dataset_snapshot_id": "数据集快照",
        "symbol": "标的",
        "timeframe": "周期",
        "status": "状态",
        "created_at": "创建时间",
        "validation_split_id": "样本切分",
        "total_return": "总收益率",
        "final_equity": "最终权益",
        "trade_count": "交易数",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
        "benchmark_return": "基准收益率",
        "excess_return": "超额收益率",
        "warning_count": "告警数",
        "order_count": "订单数",
        "fill_count": "成交数",
    }


def _comparison_column_labels() -> dict[str, str]:
    return {
        "run_id": "运行 ID",
        "strategy_name": "策略",
        "total_return": "总收益率",
        "benchmark_return": "基准收益率",
        "excess_return": "超额收益率",
        "final_equity": "最终权益",
        "trade_count": "交易数",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
    }


def _trade_column_labels() -> dict[str, str]:
    return {
        "trade_id": "交易 ID",
        "run_id": "运行 ID",
        "strategy_name": "策略",
        "dataset_snapshot_id": "数据集快照",
        "symbol": "标的",
        "side": "方向",
        "entry_time": "开仓时间",
        "entry_price": "开仓价格",
        "exit_time": "平仓时间",
        "exit_price": "平仓价格",
        "qty": "数量",
        "gross_pnl": "毛利润",
        "fee": "手续费",
        "net_pnl": "净利润",
        "return_pct": "收益率",
        "holding_bars": "持仓 K 线数",
        "entry_reason": "开仓原因",
        "exit_reason": "平仓原因",
    }


def _warning_column_labels() -> dict[str, str]:
    return {
        "warning_id": "告警 ID",
        "warning_type": "告警类型",
        "warning_code": "告警代码",
        "severity": "严重级别",
        "message": "信息",
        "created_at": "创建时间",
    }


def _parameter_lab_column_labels() -> dict[str, str]:
    return {
        "run_id": "运行 ID",
        "strategy_name": "策略",
        "dataset_snapshot_id": "数据集快照",
        "symbol": "标的",
        "timeframe": "周期",
        "validation_split_id": "样本切分",
        "status": "状态",
        "created_at": "创建时间",
        "fast_period": "快线周期",
        "slow_period": "慢线周期",
        "qty_policy_ref": "下单数量策略",
        "leverage": "杠杆",
        "fee_rate": "手续费率",
        "slippage_bps": "滑点 (bps)",
        "total_return": "总收益率",
        "benchmark_return": "基准收益率",
        "excess_return": "超额收益率",
        "final_equity": "最终权益",
        "trade_count": "交易数",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
        "warning_count": "告警数",
    }


def _status_label(value: str) -> str:
    return {
        "pending": "待执行",
        "running": "运行中",
        "success": "成功",
        "failed": "失败",
    }.get(value, value)


def _market_type_label(value: str) -> str:
    return {
        MarketType.LINEAR_USDT_PERPETUAL.value: "Linear USDT 永续",
    }.get(value, value)


def _price_type_label(value: str) -> str:
    return {
        PriceType.LAST.value: "Last Price",
    }.get(value, value)


def _timeframe_label(value: str) -> str:
    return {
        "1d": "1日",
        "4h": "4小时",
        "1h": "1小时",
        "15m": "15分钟",
    }.get(value, value)


def _benchmark_mode_label(value: str) -> str:
    return {
        "all": "全部",
        "with": "只看有基准",
        "without": "只看无基准",
    }.get(value, value)


def _sort_mode_label(value: str) -> str:
    return {
        "created_at_desc": "按创建时间",
        "total_return_desc": "按收益率",
        "trade_count_desc": "按交易数",
        "warning_count_desc": "按告警数",
    }.get(value, value)


def _trade_outcome_label(value: str) -> str:
    return {
        "all": "全部",
        "winner": "盈利",
        "loser": "亏损",
        "flat": "持平",
    }.get(value, value)


def _side_label(value: str) -> str:
    return {
        "long": "做多",
        "short": "做空",
    }.get(value, value)


def _metric_label(value: str) -> str:
    return {
        "total_return": "总收益率",
        "excess_return": "超额收益率",
        "win_rate": "胜率",
        "trade_count": "交易数",
        "profit_factor": "盈亏比",
    }.get(value, value)


def _parameter_name_label(value: str) -> str:
    return {
        "fast_period": "快线周期",
        "slow_period": "慢线周期",
    }.get(value, value)


def _strategy_label(
    value: str,
    *,
    fast_period: int | None = None,
    slow_period: int | None = None,
) -> str:
    base_label = {
        "ema_crossover": "双 EMA 交叉策略",
    }.get(value, value)
    if base_label == "双 EMA 交叉策略" and fast_period is not None and slow_period is not None:
        return f"{base_label}（{fast_period}/{slow_period}）"
    return base_label


def _qty_policy_label(value: str | None) -> str:
    if value is None:
        return "-"
    return {
        "fixed_notional_v1": "固定数量下单",
    }.get(value, value)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _warning_type_label(value: str) -> str:
    return {
        "data_warning": "数据告警",
        "execution_warning": "执行告警",
        "analytics_warning": "分析告警",
    }.get(value, value)


def _severity_label(value: str) -> str:
    return {
        "info": "提示",
        "warning": "警告",
        "error": "错误",
    }.get(value, value)


def _format_pct(value: float) -> str:
    return f"{value:.2%}"


def _format_pct_or_dash(value: float | None) -> str:
    if value is None:
        return "-"
    return _format_pct(float(value))


def _format_number(value: float, *, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _format_number_or_dash(value: float | None) -> str:
    if value is None:
        return "-"
    return _format_number(float(value))


def _format_metric_value(value: float, metric_name: str) -> str:
    if metric_name in {"total_return", "excess_return", "win_rate"}:
        return _format_pct(value)
    if metric_name == "trade_count":
        return str(int(round(value)))
    return _format_number(value)


def _float_range_bounds(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    return (min(values), max(values))


def _int_range_bounds(values: list[int]) -> tuple[int, int]:
    if not values:
        return (0, 0)
    return (min(values), max(values))


def _inline_float_slider(label: str, *, bounds: tuple[float, float], key: str) -> tuple[float, float]:
    lower, upper = bounds
    if lower == upper:
        st.caption(f"{label}：当前只有 {lower:.2f}")
        return bounds
    selected = st.slider(label, min_value=lower, max_value=upper, value=bounds, key=key)
    return float(selected[0]), float(selected[1])


def _inline_int_slider(label: str, *, bounds: tuple[int, int], key: str) -> tuple[int | None, int | None]:
    lower, upper = bounds
    if lower == upper:
        st.caption(f"{label}：当前只有 {lower}")
        return bounds
    selected = st.slider(label, min_value=lower, max_value=upper, value=bounds, key=key)
    return int(selected[0]), int(selected[1])


def _render_summary_column_picker(columns: list[str]) -> list[str]:
    preferred_columns = [
        "运行 ID",
        "策略",
        "标的",
        "周期",
        "状态",
        "总收益率",
        "超额收益率",
        "交易数",
        "告警数",
        "创建时间",
    ]
    default_columns = [column for column in preferred_columns if column in columns]
    state_key = "summary_table_columns_state"
    stored_columns = st.session_state.get(state_key, default_columns or columns)
    valid_stored_columns = [column for column in stored_columns if column in columns]
    with st.expander("显示列", expanded=False):
        selected_columns = st.multiselect(
            "显示列",
            options=columns,
            default=valid_stored_columns or default_columns or columns,
            key="summary_table_columns",
        )
    final_columns = list(selected_columns) if selected_columns else (default_columns or columns)
    st.session_state[state_key] = final_columns
    st.caption("列选择会在当前页面会话里保留。")
    return final_columns


def _paginate_rows(
    rows: list[dict[str, object]],
    *,
    key_prefix: str,
    page_size: int,
) -> tuple[list[dict[str, object]], int, int, int]:
    total_rows = len(rows)
    if total_rows == 0:
        return [], 1, 1, 0

    page_count = max(1, (total_rows + page_size - 1) // page_size)
    page_key = f"{key_prefix}_page_number"
    stored_page = int(st.session_state.get(page_key, 1))
    page_number = max(1, min(stored_page, page_count))
    st.session_state[page_key] = page_number
    start_index = (page_number - 1) * page_size
    end_index = start_index + page_size
    return rows[start_index:end_index], page_number, page_count, total_rows


def _render_table_pager(*, key_prefix: str, page_number: int, page_count: int, total_rows: int) -> None:
    page_key = f"{key_prefix}_page_number"

    def _go_prev() -> None:
        st.session_state[page_key] = max(1, int(st.session_state.get(page_key, 1)) - 1)

    def _go_next() -> None:
        st.session_state[page_key] = min(page_count, int(st.session_state.get(page_key, 1)) + 1)

    spacer, summary_col, prev_col, next_col = st.columns([8.0, 1.55, 0.72, 0.72])
    with summary_col:
        st.caption(f"共 {total_rows} 条 · 第 {page_number}/{page_count} 页")
    with prev_col:
        st.button(
            "‹ 上一页",
            key=f"{key_prefix}_prev",
            on_click=_go_prev,
            disabled=page_number <= 1,
            use_container_width=True,
        )
    with next_col:
        st.button(
            "下一页 ›",
            key=f"{key_prefix}_next",
            on_click=_go_next,
            disabled=page_number >= page_count,
            use_container_width=True,
        )


def _downsample_chart_frame(frame: pd.DataFrame, *, max_points: int) -> tuple[pd.DataFrame, int]:
    original_count = len(frame)
    if original_count <= max_points:
        return frame, original_count

    step = max(1, (original_count + max_points - 1) // max_points)
    sampled = frame.iloc[::step]
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]])
        sampled = sampled[~sampled.index.duplicated(keep="last")]
    return sampled, original_count


def _render_timeseries_chart(frame: pd.DataFrame, *, title: str) -> None:
    figure = go.Figure()
    for column in frame.columns:
        figure.add_trace(
            go.Scattergl(
                x=frame.index,
                y=frame[column],
                mode="lines",
                name=str(column),
                line={"width": 2},
                hovertemplate=f"{column}<br>时间=%{{x|%Y-%m-%d %H:%M}}<br>数值=%{{y:,.2f}}<extra></extra>",
            )
        )

    figure.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        dragmode="pan",
        hovermode="x unified",
        margin={"l": 24, "r": 24, "t": 48, "b": 82},
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.16,
            "x": 0,
            "xanchor": "left",
            "font": {"size": 11},
            "itemwidth": 90,
        },
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0.9)",
        font={"family": "IBM Plex Sans, sans-serif", "size": 12},
    )
    figure.update_xaxes(
        title_text="时间",
        tickformat="%Y-%m-%d\n%H:%M",
        showgrid=True,
        gridcolor="rgba(21, 36, 31, 0.06)",
        rangeslider={"visible": True, "thickness": 0.08},
    )
    figure.update_yaxes(
        title_text="权益",
        separatethousands=True,
        showgrid=True,
        gridcolor="rgba(21, 36, 31, 0.06)",
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        config={
            "displaylogo": False,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )


def _render_metric_chart(frame: pd.DataFrame, *, title: str) -> None:
    figure = go.Figure()
    for column in frame.columns:
        figure.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame[column],
                mode="lines+markers",
                name=str(column),
                line={"width": 2},
                marker={"size": 6},
                hovertemplate=f"{column}<br>参数=%{{x}}<br>数值=%{{y:,.4f}}<extra></extra>",
            )
        )
    figure.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        hovermode="x unified",
        margin={"l": 24, "r": 24, "t": 48, "b": 56},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0.9)",
        font={"family": "IBM Plex Sans, sans-serif", "size": 12},
    )
    figure.update_xaxes(title_text="参数取值", showgrid=True, gridcolor="rgba(21, 36, 31, 0.06)")
    figure.update_yaxes(title_text="指标值", showgrid=True, gridcolor="rgba(21, 36, 31, 0.06)")
    st.plotly_chart(
        figure,
        use_container_width=True,
        config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )


def _sort_run_summaries(summaries, *, sort_mode: str):
    sorters = {
        "created_at_desc": lambda item: item.created_at,
        "total_return_desc": lambda item: item.total_return,
        "trade_count_desc": lambda item: item.trade_count,
        "warning_count_desc": lambda item: item.warning_count,
    }
    sorter = sorters.get(sort_mode, sorters["created_at_desc"])
    return sorted(summaries, key=sorter, reverse=True)


def _run_option_label(summary) -> str:
    symbol = summary.symbol or summary.dataset_snapshot_id
    return f"{summary.run_id} · {symbol} · {_format_pct(summary.total_return)}"


def _comparison_series_label(detail) -> str:
    symbol = str(detail.manifest.resolved_config_json.get("symbol") or detail.run.dataset_snapshot_id)
    compact_symbol = symbol.replace(":USDT", "")
    run_suffix = detail.run.run_id[-6:]
    return f"{compact_symbol} · {run_suffix}"


def _render_compact_summary_bar(items: list[tuple[str, str]], *, compact: bool = False) -> None:
    class_name = "cbw-inline-meta cbw-inline-meta-compact" if compact else "cbw-inline-meta"
    cells = "".join(
        f"""
        <div class="cbw-inline-item">
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
        """
        for label, value in items
    )
    st.markdown(f'<div class="{class_name}">{cells}</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
