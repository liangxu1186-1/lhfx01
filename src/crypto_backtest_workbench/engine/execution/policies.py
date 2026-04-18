"""Default execution policies."""

from crypto_backtest_workbench.domain.models import ExecutionPolicy


DEFAULT_EXECUTION_POLICY = ExecutionPolicy(
    execution_policy_id="signal_on_bar_close_fill_on_next_bar_open",
    signal_timing="bar_close",
    fill_timing="next_bar_open",
    price_field_used="open",
    allow_same_bar_exit=False,
    version="v1",
)

