from __future__ import annotations

from pathlib import Path

import pytest

from crypto_backtest_workbench.domain.models import Side, SignalAction
from crypto_backtest_workbench.engine.strategy import EMACrossoverStrategy, StrategyInput


def test_ema_crossover_feature_specs_declare_precomputed_features() -> None:
    strategy = EMACrossoverStrategy(fast_period=5, slow_period=20)

    specs = strategy.feature_specs()

    assert len(specs) == 2
    assert specs[0].name == "ema"
    assert specs[0].params == {"window": 5}
    assert specs[0].warmup_bars == 21
    assert specs[1].params == {"window": 20}


def test_ema_crossover_generates_open_then_reverse_signals(tmp_path: Path) -> None:
    features_path = tmp_path / "ema_features.csv"
    features_path.write_text(
        "\n".join(
            [
                "timestamp,ema_close_5,ema_close_20",
                "2024-01-01T00:00:00+00:00,99,100",
                "2024-01-01T01:00:00+00:00,101,100",
                "2024-01-01T02:00:00+00:00,102,101",
                "2024-01-01T03:00:00+00:00,100,101",
                "2024-01-01T04:00:00+00:00,99,100",
            ]
        ),
        encoding="utf-8",
    )
    strategy = EMACrossoverStrategy(fast_period=5, slow_period=20)
    strategy_input = StrategyInput(
        run_id="run-1",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        feature_artifact_id="feature-1",
        features_uri=features_path.as_uri(),
        config={"qty_policy_ref": "risk_fixed_fraction_v1"},
    )

    signals = strategy.generate_signals(strategy_input)

    assert len(signals) == 2
    assert signals[0].action == SignalAction.OPEN
    assert signals[0].side == Side.LONG
    assert signals[0].reason_code == "ema_bullish_crossover"
    assert signals[0].qty_policy_ref == "risk_fixed_fraction_v1"
    assert signals[0].meta_json["fast_column"] == "ema_close_5"
    assert signals[1].action == SignalAction.REVERSE
    assert signals[1].side == Side.SHORT
    assert signals[1].reason_code == "ema_bearish_crossover"


def test_ema_crossover_rejects_missing_feature_columns(tmp_path: Path) -> None:
    features_path = tmp_path / "ema_features.csv"
    features_path.write_text(
        "\n".join(
            [
                "timestamp,ema_close_20",
                "2024-01-01T00:00:00+00:00,100",
                "2024-01-01T01:00:00+00:00,101",
            ]
        ),
        encoding="utf-8",
    )
    strategy = EMACrossoverStrategy(fast_period=5, slow_period=20)
    strategy_input = StrategyInput(
        run_id="run-1",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        feature_artifact_id="feature-1",
        features_uri=str(features_path),
    )

    with pytest.raises(ValueError, match="missing required columns"):
        strategy.generate_signals(strategy_input)
