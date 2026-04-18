"""Minimal read-only Streamlit page for Phase 1 run results."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

from crypto_backtest_workbench.app.readmodels import (
    build_equity_chart_rows,
    build_multi_run_equity_rows,
    build_run_comparison_views,
    build_trade_explorer_rows,
    build_trade_rows,
    build_warning_rows,
    TradeFilter,
    filter_trade_rows,
    filter_run_summary_views,
    list_run_summary_views,
    load_run_detail_view,
)
from crypto_backtest_workbench.storage.repositories import FileRunRepository


def main() -> None:
    st.set_page_config(page_title="加密回测工作台", layout="wide")
    _apply_page_chrome()

    args = _parse_args(sys.argv[1:])
    data_dir = _resolve_data_dir(repository_root=args.repository_root, data_dir=args.data_dir)
    repository = FileRunRepository(data_dir)
    summaries = list_run_summary_views(repository)

    _render_page_header(data_dir=data_dir)

    if not summaries:
        st.info("当前还没有已落盘的回测结果。先执行 `cbw ingest` 和 `cbw run-ema` 生成一组 run。")
        return

    filtered_summaries = _render_dashboard_filters(summaries)
    if not filtered_summaries:
        st.warning("当前筛选条件下没有匹配的 run。")
        return

    _render_summary_cards(filtered_summaries)
    workspace_col, inspector_col = st.columns([1.78, 0.92], gap="large")
    with inspector_col:
        selected_run_id, selected_compare_ids = _render_run_inspector_controls(
            summaries=filtered_summaries,
            total_run_count=len(summaries),
        )

    detail = load_run_detail_view(repository, selected_run_id)
    selected_compare_details = [
        load_run_detail_view(repository, run_id)
        for run_id in list(dict.fromkeys(selected_compare_ids))
    ]

    with workspace_col:
        _render_summary_table(filtered_summaries)
        _render_comparison_section(repository, selected_compare_ids)
        _render_trade_explorer_section(selected_compare_details)

    with inspector_col:
        _render_run_inspector(detail)

    _render_detail_tabs(detail)


def _render_dashboard_filters(summaries):
    strategy_options = sorted({summary.strategy_name for summary in summaries})
    status_options = sorted({summary.status for summary in summaries})

    st.sidebar.subheader("筛选")
    selected_strategies = set(
        st.sidebar.multiselect(
            "策略",
            options=strategy_options,
            default=strategy_options,
        )
    )
    selected_statuses = set(
        st.sidebar.multiselect(
            "状态",
            options=status_options,
            default=status_options,
            format_func=_status_label,
        )
    )
    dataset_query = st.sidebar.text_input("Run / 数据集 模糊搜索")

    return filter_run_summary_views(
        summaries,
        strategy_names=selected_strategies or None,
        statuses=selected_statuses or None,
        dataset_query=dataset_query or None,
    )


def _render_summary_cards(filtered_summaries) -> None:
    returns = [summary.total_return for summary in filtered_summaries]
    trade_counts = [summary.trade_count for summary in filtered_summaries]
    best_return = max(returns)
    avg_return = sum(returns) / len(returns)
    avg_trades = sum(trade_counts) / len(trade_counts)

    cols = st.columns(4, gap="large")
    _render_stat_block(cols[0], "筛选后 Run 数", str(len(filtered_summaries)))
    _render_stat_block(cols[1], "最佳收益率", f"{best_return:.2%}")
    _render_stat_block(cols[2], "平均收益率", f"{avg_return:.2%}")
    _render_stat_block(cols[3], "平均交易数", f"{avg_trades:.1f}")


def _render_summary_table(filtered_summaries) -> None:
    summary_df = pd.DataFrame([summary.as_dict() for summary in filtered_summaries])
    if not summary_df.empty:
        summary_df["created_at"] = pd.to_datetime(summary_df["created_at"], utc=True)
        summary_df["status"] = summary_df["status"].map(_status_label)
        summary_df["total_return"] = summary_df["total_return"].map(_format_pct)
        summary_df["benchmark_return"] = summary_df["benchmark_return"].map(_format_pct_or_dash)
        summary_df["final_equity"] = summary_df["final_equity"].map(_format_number)
        summary_df = summary_df.rename(columns=_summary_column_labels())
    _section_header("运行总览", "筛选后的运行结果列表。先看收益、状态和交易数，再决定下钻哪组 run。")
    st.dataframe(summary_df, hide_index=True, use_container_width=True)


def _render_run_inspector_controls(*, summaries, total_run_count: int) -> tuple[str, list[str]]:
    st.markdown('<div class="cbw-panel">', unsafe_allow_html=True)
    _section_header("当前聚焦", "右侧面板固定当前 run 的上下文。先选一个聚焦 run，再决定要不要拉几个 run 一起比较。")
    selected_run_id = st.selectbox(
        "聚焦运行",
        options=[summary.run_id for summary in summaries],
        index=0,
    )
    selected_compare_ids = st.multiselect(
        "加入对比",
        options=[summary.run_id for summary in summaries],
        default=[selected_run_id],
    )
    selected_summary = next(summary for summary in summaries if summary.run_id == selected_run_id)
    st.caption(f"筛选结果 {len(summaries)} / 全部 {total_run_count} 个 run")
    _render_stat_block(st, "当前策略", selected_summary.strategy_name)
    _render_stat_block(st, "当前状态", _status_label(selected_summary.status))
    _render_stat_block(st, "当前收益率", _format_pct(selected_summary.total_return))
    _render_stat_block(st, "当前交易数", str(selected_summary.trade_count))
    st.markdown("</div>", unsafe_allow_html=True)
    if not selected_compare_ids:
        selected_compare_ids = [selected_run_id]
    return selected_run_id, selected_compare_ids


def _render_run_inspector(detail) -> None:
    st.markdown('<div class="cbw-panel cbw-panel-tight">', unsafe_allow_html=True)
    _section_header("运行检查器", "查看当前 run 的身份、数据来源和最重要的运行指标。这里是快速判断，不替代下方的详细标签页。")
    st.markdown(
        f"""
        <div class="cbw-inspector-list">
          <div><span>运行 ID</span><strong>{detail.run.run_id}</strong></div>
          <div><span>策略</span><strong>{detail.run.strategy_name}</strong></div>
          <div><span>数据集</span><strong>{detail.run.dataset_snapshot_id}</strong></div>
          <div><span>状态</span><strong>{_status_label(detail.run.status.value)}</strong></div>
          <div><span>样本切分</span><strong>{detail.run.validation_split_id}</strong></div>
          <div><span>特征产物</span><strong>{detail.run.feature_artifact_id}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_stat_block(st, "最终权益", _format_number(detail.metrics.final_equity))
    _render_stat_block(st, "总收益率", _format_pct(detail.metrics.total_return))
    _render_stat_block(st, "胜率", _format_pct(detail.metrics.win_rate))
    _render_stat_block(st, "盈亏比", _format_number_or_dash(detail.metrics.profit_factor))
    _render_stat_block(st, "告警数", str(len(detail.execution.warnings)))
    st.markdown("</div>", unsafe_allow_html=True)


def _render_comparison_section(repository: FileRunRepository, selected_compare_ids: list[str]) -> None:
    compare_ids = list(dict.fromkeys(selected_compare_ids))
    if not compare_ids:
        return

    details = [load_run_detail_view(repository, run_id) for run_id in compare_ids]
    comparison_df = pd.DataFrame(
        [row.as_dict() for row in build_run_comparison_views(details)]
    )
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
            columns={column: column.replace("_equity", " 策略权益") for column in numeric_columns}
        )
        chart_columns = [column.replace("_equity", " 策略权益") for column in numeric_columns]
        st.line_chart(equity_compare_df[chart_columns], use_container_width=True)


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

    trade_df = pd.DataFrame(filtered_rows)
    trade_df["side"] = trade_df["side"].map(_side_label)
    trade_df["gross_pnl"] = trade_df["gross_pnl"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["fee"] = trade_df["fee"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["net_pnl"] = trade_df["net_pnl"].map(lambda value: _format_number(float(value), digits=4))
    trade_df["return_pct"] = trade_df["return_pct"].map(lambda value: _format_pct(float(value)))
    trade_df = trade_df.rename(columns=_trade_column_labels())
    st.dataframe(trade_df, hide_index=True, use_container_width=True)


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
    cols = st.columns(5)
    _render_stat_block(cols[0], "策略", detail.run.strategy_name)
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
        st.line_chart(chart_df[chart_columns], use_container_width=True)


def _render_detail_trades(detail) -> None:
    _section_header("交易明细", "查看每笔交易的方向、进出场价格、手续费和收益。")
    trade_df = pd.DataFrame(build_trade_rows(detail))
    if trade_df.empty:
        st.info("当前 run 没有已平仓交易。")
    else:
        trade_df["side"] = trade_df["side"].map(_side_label)
        trade_df["gross_pnl"] = trade_df["gross_pnl"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["fee"] = trade_df["fee"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["net_pnl"] = trade_df["net_pnl"].map(lambda value: _format_number(float(value), digits=4))
        trade_df["return_pct"] = trade_df["return_pct"].map(lambda value: _format_pct(float(value)))
        trade_df = trade_df.rename(columns=_trade_column_labels())
        st.dataframe(trade_df, hide_index=True, use_container_width=True)


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

    with st.expander("运行清单 / 配置", expanded=True):
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
            padding-top: 2.25rem;
            padding-bottom: 2.4rem;
            max-width: 1400px;
        }
        .cbw-hero {
            position: relative;
            overflow: hidden;
            padding: 2rem 2rem 1.6rem 2rem;
            border: 1px solid var(--cbw-border);
            background:
                linear-gradient(135deg, rgba(255,255,255,0.96), rgba(246,250,247,0.92)),
                linear-gradient(180deg, rgba(13,138,114,0.05), transparent);
            border-radius: 28px;
            box-shadow: 0 18px 48px rgba(16, 31, 26, 0.08);
            margin-bottom: 1.4rem;
        }
        .cbw-hero::after {
            content: "";
            position: absolute;
            inset: auto -5% -35% auto;
            width: 420px;
            height: 420px;
            background: radial-gradient(circle, rgba(13,138,114,0.12), transparent 62%);
            pointer-events: none;
        }
        .cbw-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.35rem 0.8rem;
            border-radius: 999px;
            background: rgba(13, 138, 114, 0.08);
            color: var(--cbw-accent);
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-weight: 600;
        }
        .cbw-hero h1 {
            margin: 0.85rem 0 0 0;
            font-size: clamp(2.7rem, 4vw, 4.6rem);
            line-height: 0.95;
            letter-spacing: -0.045em;
            font-weight: 700;
        }
        .cbw-hero p {
            margin: 0.8rem 0 0 0;
            max-width: 42rem;
            color: var(--cbw-muted);
            font-size: 1rem;
            line-height: 1.6;
        }
        .cbw-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.65rem;
            margin-top: 1rem;
        }
        .cbw-chip {
            padding: 0.45rem 0.8rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.78);
            border: 1px solid var(--cbw-border);
            color: var(--cbw-ink);
            font-size: 0.84rem;
        }
        .cbw-section-head {
            margin-top: 1.35rem;
            margin-bottom: 0.65rem;
        }
        .cbw-section-head h3 {
            margin: 0;
            font-size: 1.12rem;
            letter-spacing: -0.02em;
        }
        .cbw-section-head p {
            margin: 0.2rem 0 0 0;
            color: var(--cbw-muted);
            font-size: 0.92rem;
        }
        .cbw-stat {
            padding: 0.2rem 0 0.9rem 0;
            border-top: 1px solid rgba(13, 138, 114, 0.18);
        }
        .cbw-stat-label {
            color: var(--cbw-muted);
            font-size: 0.8rem;
            margin-bottom: 0.3rem;
        }
        .cbw-stat-value {
            font-size: 1.45rem;
            font-weight: 650;
            letter-spacing: -0.03em;
            color: var(--cbw-ink);
        }
        .cbw-panel {
            padding: 1.15rem 1.2rem 1rem 1.2rem;
            border-radius: 22px;
            border: 1px solid var(--cbw-border);
            background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(248,250,247,0.88));
            box-shadow: 0 12px 32px rgba(17, 28, 24, 0.05);
            margin-bottom: 1rem;
        }
        .cbw-panel-tight {
            position: sticky;
            top: 1rem;
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
        [data-testid="stMetric"] {
            background: transparent;
            border: none;
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
          <div class="cbw-kicker">Phase 1 · Research Console</div>
          <h1>加密回测工作台</h1>
          <p>当前页面只负责读取已落盘结果。先用命令行生成数据和回测，再在这里做筛选、对比和交易下钻。</p>
          <div class="cbw-meta">
            <div class="cbw-chip">数据目录：{data_dir}</div>
            <div class="cbw-chip">模式：只读分析</div>
            <div class="cbw-chip">重点：运行总览 / 交易浏览 / 单次下钻</div>
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
        "status": "状态",
        "created_at": "创建时间",
        "total_return": "总收益率",
        "final_equity": "最终权益",
        "trade_count": "交易数",
        "benchmark_return": "基准收益率",
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


def _status_label(value: str) -> str:
    return {
        "pending": "待执行",
        "running": "运行中",
        "success": "成功",
        "failed": "失败",
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


if __name__ == "__main__":
    main()
