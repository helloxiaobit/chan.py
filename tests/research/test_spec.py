import json

import pytest

from ModelStrategy.research.boundary import ResearchBoundaryError
from ModelStrategy.research.spec import load_spec


def minimal_spec(**overrides):
    inputs = {
        "s1_trades": "from_session_b/cache_2125_S1.json",
        "s2_trades": "cache_2125_S2py10_ispyr.json",
        "bars_db": "btc_mlv.db",
    }
    if "s1_path" in overrides:
        inputs["s1_trades"] = overrides.pop("s1_path")
    window = {
        "begin": "2021-01-01",
        "end_exclusive": overrides.pop("end_exclusive", "2026-01-01"),
    }
    value = {
        "schema_version": 1,
        "strategy_id": "freeze_v4",
        "execution_model": "legacy-v1",
        "window": window,
        "inputs": inputs,
        "risk_grid": [0.005, 0.0075, 0.01],
        "portfolio": {
            "taker_fee": 0.0005,
            "maker_fee": 0.0002,
            "max_concurrent": 4,
            "max_leverage": 3.0,
            "max_pos_leverage": 1.5,
            "target_max_drawdown": 0.25,
        },
        "conviction": {
            "co_dir_mult": 1.5,
            "opp_dir_mult": 1.0,
            "bs_mults": {"1": 0.8, "1p": 1.2},
            "mult_cap": 2.0,
        },
        "zlimit": {
            "patience": 8,
            "s1_level": "K_60M",
            "s1_ms": 3600000,
            "s2_level": "K_4H",
            "s2_ms": 14400000,
        },
        "splits": {
            "A(21-23)": ["2021-01-01", "2024-01-01"],
            "B(2024)": ["2024-01-01", "2025-01-01"],
            "C(2025)": ["2025-01-01", "2026-01-01"],
        },
    }
    value.update(overrides)
    return value


def write_spec(tmp_path, value):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_load_spec_exposes_validated_values(tmp_path):
    spec = load_spec(write_spec(tmp_path, minimal_spec()))
    assert spec.strategy_id == "freeze_v4"
    assert spec.execution_model == "legacy-v1"
    assert spec.risk_grid == (0.005, 0.0075, 0.01)
    assert spec.inputs["bars_db"].as_posix() == "btc_mlv.db"


def test_spec_rejects_absolute_input_path(tmp_path):
    path = write_spec(tmp_path, minimal_spec(s1_path="C:/private/cache.json"))
    with pytest.raises(ValueError, match="relative"):
        load_spec(path)


def test_spec_rejects_parent_path_escape(tmp_path):
    path = write_spec(tmp_path, minimal_spec(s1_path="../cache.json"))
    with pytest.raises(ValueError, match="relative"):
        load_spec(path)


def test_spec_rejects_oos_window(tmp_path):
    path = write_spec(tmp_path, minimal_spec(end_exclusive="2026-01-02"))
    with pytest.raises(ResearchBoundaryError):
        load_spec(path)


def test_spec_rejects_non_increasing_risk_grid(tmp_path):
    path = write_spec(tmp_path, minimal_spec(risk_grid=[0.01, 0.005]))
    with pytest.raises(ValueError, match="risk_grid"):
        load_spec(path)
