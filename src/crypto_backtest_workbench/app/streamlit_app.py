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
    build_trade_rows,
    build_warning_rows,
    list_run_summary_views,
    load_run_detail_view,
)
from crypto_backtest_workbench.storage.repositories import FileRunRepository


def main() -> None:
    st.set_page_config(page_title="CBW Phase 1", layout="wide")

    args = _parse_args(sys.argv[1:])
    data_dir = _resolve_data_dir(repository_root=args.repository_root, data_dir=args.data_dir)
    repository = FileRunRepository(data_dir)
    summaries = list_run_summary_views(repository)

    st.title("Crypto Backtest Workbench")
    st.caption(f"只读结果页，当前数据目录：`{data_dir}`")

    if not summaries:
        st.info("当前还没有已落盘的 run 结果。先执行 `cbw ingest` 和 `cbw run-ema`。")
        return

    selected_run_id = st.sidebar.selectbox(
        "选择 Run",
        options=[summary.run_id for summary in summaries],
        index=0,
    )
    st.sidebar.caption(f"共 {len(summaries)} 个 run")

    summary_df = pd.DataFrame([summary.as_dict() for summary in summaries])
    if not summary_df.empty:
        summary_df["created_at"] = pd.to_datetime(summary_df["created_at"], utc=True)
    st.subheader("Run Summary")
    st.dataframe(summary_df, hide_index=True, use_container_width=True)

    detail = load_run_detail_view(repository, selected_run_id)
    _render_detail(detail)


def _render_detail(detail) -> None:
    st.subheader(f"Run Detail: {detail.run.run_id}")
    cols = st.columns(5)
    cols[0].metric("Strategy", detail.run.strategy_name)
    cols[1].metric("Trade Count", str(detail.metrics.trade_count))
    cols[2].metric("Total Return", f"{detail.metrics.total_return:.2%}")
    cols[3].metric("Final Equity", f"{detail.metrics.final_equity:.2f}")
    benchmark_return = None
    if detail.benchmark is not None:
        benchmark_return = detail.benchmark.result.return_pct
    cols[4].metric(
        "Benchmark Return",
        "-" if benchmark_return is None else f"{benchmark_return:.2%}",
    )

    st.caption(
        f"dataset={detail.run.dataset_snapshot_id} | "
        f"status={detail.run.status.value} | "
        f"validation_split={detail.run.validation_split_id}"
    )

    chart_rows = build_equity_chart_rows(detail)
    chart_df = pd.DataFrame(chart_rows)
    st.subheader("Equity")
    if chart_df.empty:
        st.info("当前 run 没有 equity 曲线数据。")
    else:
        chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], utc=True)
        chart_df = chart_df.set_index("timestamp")
        chart_columns = ["strategy_equity"]
        if chart_df["benchmark_equity"].notna().any():
            chart_columns.append("benchmark_equity")
        st.line_chart(chart_df[chart_columns], use_container_width=True)

    st.subheader("Trades")
    trade_df = pd.DataFrame(build_trade_rows(detail))
    if trade_df.empty:
        st.info("当前 run 没有 closed trades。")
    else:
        st.dataframe(trade_df, hide_index=True, use_container_width=True)

    st.subheader("Warnings")
    warning_df = pd.DataFrame(build_warning_rows(detail))
    if warning_df.empty:
        st.caption("当前 run 没有 warnings。")
    else:
        st.dataframe(warning_df, hide_index=True, use_container_width=True)

    with st.expander("Manifest / Run Config", expanded=False):
        st.json(
            {
                "manifest": _json_ready(asdict(detail.manifest)),
                "run": _json_ready(asdict(detail.run)),
            }
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


if __name__ == "__main__":
    main()
