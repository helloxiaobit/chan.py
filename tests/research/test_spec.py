import json
from pathlib import Path

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


def conservative_spec(**overrides):
    value = minimal_spec()
    value["execution_model"] = "conservative-v2"
    value["inputs"]["funding_rates"] = "btc/btc_funding_rate.csv"
    value["execution"] = {
        "source_timestamp_offset_seconds": 0,
        "mark_level": "K_60M",
        "mark_ms": 3600000,
        "entry_patience": 8,
        "stop_slippage": 0.0005,
        "same_bar_policy": "adverse_first",
        "funding_order": "before_close",
        "funding_interval_ms": 28800000,
        "market_gap_policy": "carry_forward",
        "max_mark_gap_intervals": 16,
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


def test_legacy_spec_has_no_execution_policy(tmp_path):
    spec = load_spec(write_spec(tmp_path, minimal_spec()))
    assert spec.execution == {}


def test_conservative_spec_requires_funding_input_and_policy(tmp_path):
    spec = load_spec(write_spec(tmp_path, conservative_spec()))
    assert spec.execution_model == "conservative-v2"
    assert spec.inputs["funding_rates"].as_posix() == "btc/btc_funding_rate.csv"
    assert spec.execution["mark_level"] == "K_60M"
    assert spec.execution["funding_interval_ms"] == 28800000
    assert spec.execution["market_gap_policy"] == "carry_forward"
    assert spec.execution["max_mark_gap_intervals"] == 16
    assert spec.execution["source_timestamp_offset_seconds"] == 0


def test_tracked_conservative_spec_declares_historical_utc_correction():
    root = Path(__file__).resolve().parents[2]
    spec = load_spec(
        root
        / "ModelStrategy"
        / "research"
        / "configs"
        / "freeze_v4_conservative_v2.json"
    )
    assert spec.execution["source_timestamp_offset_seconds"] == 28800


def test_tracked_conservative_spec_changes_only_execution_assumptions():
    root = Path(__file__).resolve().parents[2]
    config_root = root / "ModelStrategy" / "research" / "configs"
    legacy = json.loads(
        (config_root / "freeze_v4_legacy_v1.json").read_text(encoding="utf-8")
    )
    conservative = json.loads(
        (config_root / "freeze_v4_conservative_v2.json").read_text(
            encoding="utf-8"
        )
    )
    conservative.pop("execution")
    conservative["execution_model"] = "legacy-v1"
    conservative["inputs"].pop("funding_rates")
    assert conservative == legacy


def test_conservative_spec_rejects_unknown_execution_key(tmp_path):
    value = conservative_spec()
    value["execution"]["optimistic_fill"] = True
    with pytest.raises(ValueError, match="execution keys"):
        load_spec(write_spec(tmp_path, value))


def test_conservative_spec_requires_execution_policy(tmp_path):
    value = conservative_spec()
    del value["execution"]
    with pytest.raises(ValueError, match="execution"):
        load_spec(write_spec(tmp_path, value))


def test_conservative_spec_requires_matching_entry_patience(tmp_path):
    value = conservative_spec()
    value["execution"]["entry_patience"] = 7
    with pytest.raises(ValueError, match="entry_patience.*zlimit"):
        load_spec(write_spec(tmp_path, value))


def test_conservative_spec_rejects_unbounded_mark_gap_policy(tmp_path):
    value = conservative_spec()
    value["execution"]["max_mark_gap_intervals"] = None
    with pytest.raises(ValueError, match="max_mark_gap_intervals"):
        load_spec(write_spec(tmp_path, value))


@pytest.mark.parametrize("offset", [28800.0, True, 90000, -90000])
def test_conservative_spec_rejects_ambiguous_timestamp_offset(
    tmp_path, offset
):
    value = conservative_spec()
    value["execution"]["source_timestamp_offset_seconds"] = offset
    with pytest.raises(ValueError, match="source_timestamp_offset_seconds"):
        load_spec(write_spec(tmp_path, value))


def test_legacy_spec_rejects_conservative_only_input(tmp_path):
    value = minimal_spec()
    value["inputs"]["funding_rates"] = "btc/btc_funding_rate.csv"
    with pytest.raises(ValueError, match="inputs keys"):
        load_spec(write_spec(tmp_path, value))


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
