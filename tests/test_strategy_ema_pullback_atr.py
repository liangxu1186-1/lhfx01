from __future__ import annotations

from pathlib import Path

import pytest

from crypto_backtest_workbench.domain.models import Side, SignalAction
from crypto_backtest_workbench.engine.strategy import EMAPullbackATRStrategy, StrategyInput


def test_ema_pullback_atr_feature_specs_and_warmup() -> None:
    strategy = EMAPullbackATRStrategy(
        trend_fast_period=8,
        trend_slow_period=34,
        atr_entry_tolerance=0.5,
        atr_stop_mult=1.5,
        risk_reward_ratio=2.0,
    )

    specs = strategy.feature_specs()

    assert strategy.name == "ema_pullback_atr_v2"
    assert strategy.version == "v2"
    assert strategy.warmup_bars == 54
    assert [spec.name for spec in specs] == ["ema", "ema", "ema", "atr"]
    assert [spec.params["window"] for spec in specs] == [8, 34, 21, 14]
    assert all(spec.warmup_bars == 54 for spec in specs)


def test_ema_pullback_atr_generates_long_open(tmp_path: Path) -> None:
    strategy = _strategy()
    features_path = _write_features(
        tmp_path,
        [
            "2024-01-01T00:00:00+00:00,100,105,99,104,110,100,100,10",
            "2024-01-01T01:00:00+00:00,104,107,100.5,106,111,100,101,10",
        ],
    )

    signals = strategy.generate_signals(_input(features_path))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.action == SignalAction.OPEN
    assert signal.side == Side.LONG
    assert signal.reason_code == "ema_pullback_atr_long_breakout"
    assert signal.meta_json["risk_spec"]["atr_value"] == 10.0


def test_ema_pullback_atr_signal_filters_are_optional_and_can_block_entries(tmp_path: Path) -> None:
    unfiltered = _strategy()
    filtered = _strategy(
        signal_filters=(
            {
                "filter_type": "adx",
                "enabled": True,
                "params": {"adx_period": 14, "min_adx": 20},
            },
        )
    )
    features_path = _write_features(
        tmp_path,
        [
            "2024-01-01T00:00:00+00:00,100,105,99,104,110,100,100,10,10",
            "2024-01-01T01:00:00+00:00,104,107,100.5,106,111,100,101,10,10",
        ],
        extra_columns=("adx_14",),
    )

    assert len(unfiltered.generate_signals(_input(features_path))) == 1
    assert filtered.generate_signals(_input(features_path)) == []


def test_ema_pullback_atr_generates_short_open(tmp_path: Path) -> None:
    strategy = _strategy()
    features_path = _write_features(
        tmp_path,
        [
            "2024-01-01T00:00:00+00:00,100,101,95,96,90,100,100,10",
            "2024-01-01T01:00:00+00:00,96,99.5,92,94,89,100,99,10",
        ],
    )

    signals = strategy.generate_signals(_input(features_path))

    assert len(signals) == 1
    assert signals[0].action == SignalAction.OPEN
    assert signals[0].side == Side.SHORT
    assert signals[0].reason_code == "ema_pullback_atr_short_breakdown"


def test_ema_pullback_atr_skips_when_atr_too_small(tmp_path: Path) -> None:
    strategy = _strategy(min_atr_pct_of_price=0.1)
    features_path = _write_features(
        tmp_path,
        [
            "2024-01-01T00:00:00+00:00,100,105,99,104,110,100,100,1",
            "2024-01-01T01:00:00+00:00,104,107,100.5,106,111,100,101,1",
        ],
    )

    assert strategy.generate_signals(_input(features_path)) == []


def test_ema_pullback_atr_only_generates_open_not_reverse(tmp_path: Path) -> None:
    strategy = _strategy()
    features_path = _write_features(
        tmp_path,
        [
            "2024-01-01T00:00:00+00:00,100,105,99,104,110,100,100,10",
            "2024-01-01T01:00:00+00:00,104,107,100.5,106,111,100,101,10",
            "2024-01-01T02:00:00+00:00,106,109,102,108,112,100,103,10",
        ],
    )

    signals = strategy.generate_signals(_input(features_path))

    assert len(signals) == 2
    assert all(signal.action == SignalAction.OPEN for signal in signals)


def test_ema_pullback_atr_validates_parameters() -> None:
    with pytest.raises(ValueError, match="trend_fast_period must be smaller"):
        EMAPullbackATRStrategy(
            trend_fast_period=34,
            trend_slow_period=8,
            atr_entry_tolerance=0.5,
            atr_stop_mult=1.5,
            risk_reward_ratio=2.0,
        )


def _strategy(**overrides) -> EMAPullbackATRStrategy:
    params = {
        "trend_fast_period": 8,
        "trend_slow_period": 34,
        "atr_entry_tolerance": 0.5,
        "atr_stop_mult": 1.5,
        "risk_reward_ratio": 2.0,
        "entry_ema_period": 21,
        "atr_period": 14,
        "min_atr_pct_of_price": 0.002,
    }
    params.update(overrides)
    return EMAPullbackATRStrategy(**params)


def _write_features(tmp_path: Path, rows: list[str], *, extra_columns: tuple[str, ...] = ()) -> Path:
    features_path = tmp_path / "features.csv"
    features_path.write_text(
        "\n".join(
            [
                ",".join(["timestamp", "open", "high", "low", "close", "ema_close_8", "ema_close_34", "ema_close_21", "atr_14", *extra_columns]),
                *rows,
            ]
        ),
        encoding="utf-8",
    )
    return features_path


def _input(features_path: Path) -> StrategyInput:
    return StrategyInput(
        run_id="run-v2",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        feature_artifact_id="feature-v2",
        features_uri=features_path.as_uri(),
        config={"qty_policy_ref": "percent_of_cash"},
    )
