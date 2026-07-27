import json
from pathlib import Path

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.certification_spec import load_certification_spec


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_SPEC = (
    REPO_ROOT
    / "ModelStrategy"
    / "research"
    / "configs"
    / "freeze_v5_candidate_v1.json"
)


def test_tracked_v5_candidate_and_gates_are_preregistered():
    spec = load_certification_spec(TRACKED_SPEC)
    assert spec.strategy_id == "freeze_v5_candidate_v1"
    assert spec.execution_model == "conservative-v2"
    assert spec.components == (
        "S1bz[4H,1H,15M]",
        "S2py10[1D,4H]",
        "conviction#14",
        "z-limit(S2 non-pyramid)",
        "z-exit",
    )
    assert spec.symbols == (
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
    )
    assert spec.begin_ts == parse_utc("2021-01-01")
    assert spec.end_ts == parse_utc("2026-01-01")
    assert spec.oos_begin_ts == parse_utc("2026-01-01")
    assert spec.oos_end_ts == parse_utc("2026-07-27")
    assert spec.gates["btc"] == {
        "full_calmar_min": 2.0,
        "split_cagr_min_exclusive": 0.0,
        "max_drawdown": 0.25,
    }
    assert spec.gates["robustness"] == {
        "full_cagr_min_exclusive": 0.0,
        "split_cagr_min": -0.01,
        "max_drawdown": 0.35,
    }
    assert spec.gates["multi"] == {
        "cagr_min_exclusive": 0.0,
        "max_drawdown": 0.25,
        "calmar_min": 1.0,
        "max_concurrent": 16,
    }
    assert spec.gates["oos"] == {
        "cagr_min_exclusive": 0.5,
        "max_drawdown_exclusive": 0.25,
        "calmar_min": 2.0,
    }
    assert spec.stacks["s1"]["entry_kind"] == "strategy_fill"
    assert spec.stacks["s2"]["entry_kind"] == "signal_intent"
    assert spec.exit_policy["eligible_reasons"] == (
        "reverse_bsp",
        "trend_flip",
        "time_stop",
    )
    assert spec.execution["source_timestamp_offset_seconds"] == 0


def write_changed_spec(tmp_path, change):
    value = json.loads(TRACKED_SPEC.read_text(encoding="utf-8"))
    change(value)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda value: value.update({"extra": 1}), "keys"),
        (
            lambda value: value["components"].reverse(),
            "components",
        ),
        (
            lambda value: value["gates"]["btc"].update(
                {"max_drawdown": 0.3}
            ),
            "gates.btc",
        ),
        (
            lambda value: value["inputs"]["symbols"]["BTC/USDT"].update(
                {"s1_trades": "../outside.json"}
            ),
            "relative path",
        ),
        (
            lambda value: value["execution"].update(
                {"same_bar_policy": "optimistic"}
            ),
            "same_bar_policy",
        ),
        (
            lambda value: value["execution"].update(
                {"source_timestamp_offset_seconds": 28800}
            ),
            "source_timestamp_offset_seconds",
        ),
        (
            lambda value: value["oos_window"].update(
                {"end_exclusive": "2026-07-28"}
            ),
            "oos_window",
        ),
    ],
)
def test_v5_spec_rejects_gate_component_path_or_execution_drift(
    tmp_path, change, match
):
    with pytest.raises(ValueError, match=match):
        load_certification_spec(write_changed_spec(tmp_path, change))
