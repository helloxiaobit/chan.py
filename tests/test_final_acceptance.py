import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "ModelStrategy" / "research" / "baselines"
CONFIGS = ROOT / "ModelStrategy" / "research" / "configs"
REPORT = (
    ROOT
    / "docs"
    / "superpowers"
    / "reports"
    / "2026-07-28-final-acceptance.md"
)
REPORT_LINK = "docs/superpowers/reports/2026-07-28-final-acceptance.md"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_final_strategy_decision_matches_tracked_references():
    v4 = load_json(BASELINES / "freeze_v4_conservative_v2.json")
    v5 = load_json(BASELINES / "freeze_v5_candidate_v1_is.json")
    spec = load_json(CONFIGS / "freeze_v5_candidate_v1.json")

    assert v4["execution_model"] == "conservative-v2"
    assert v4["risk_pct"] == pytest.approx(0.005)
    assert v5["execution_model"] == "conservative-v2"
    assert v5["selected_risk_pct"] == pytest.approx(0.005)
    assert v5["status"] == "rejected"
    assert v5["stop_reason"] == "btc_full_calmar"
    assert v5["btc"]["cagr"] == pytest.approx(0.3195696056666606)
    assert v5["btc"]["full_dd"] == pytest.approx(0.19806622309040048)
    assert v5["btc"]["calmar"] == pytest.approx(1.6134482734131004)
    assert v5["unopened_tiers"] == [
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
        "shared_multi",
        "OOS",
    ]
    assert spec["window"] == {
        "begin": "2021-01-01",
        "end_exclusive": "2026-01-01",
    }
    assert spec["gates"]["btc"]["full_calmar_min"] == 2.0


def test_final_documents_derive_the_same_v5_numbers_and_status():
    v5 = load_json(BASELINES / "freeze_v5_candidate_v1_is.json")
    expected = (
        f"{v5['btc']['cagr']:.3%}",
        f"{v5['btc']['full_dd']:.3%}",
        f"{v5['btc']['calmar']:.3f}",
        v5["status"],
        "2021-01-01",
        "2026-01-01",
        "conservative-v2",
    )
    documents = [
        ROOT / "README_FULL.md",
        ROOT / "STRATEGY_LOG.md",
        REPORT,
    ]
    for path in documents:
        text = path.read_text(encoding="utf-8")
        for value in expected:
            assert value in text, f"{path.name} 缺少冻结值 {value}"


def test_final_report_and_operator_docs_keep_trading_unapproved():
    report = REPORT.read_text(encoding="utf-8")
    readme = (ROOT / "README_FULL.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    strategy_log = (ROOT / "STRATEGY_LOG.md").read_text(encoding="utf-8")

    assert "research/dry-run accepted; testnet/live not approved" in report
    assert "CHANPY_ENABLE_TESTNET=YES" in report
    assert "CHANPY_LIVE_TRADING_UNLOCK=I_ACCEPT_REAL_ORDERS" in report
    assert "CHANPY_KILL_SWITCH=1" in report
    assert "status=candidate" in report
    assert "testnet approved" not in report.lower()
    assert "live approved" not in report.lower()
    assert REPORT_LINK in readme
    assert REPORT_LINK in claude
    assert REPORT_LINK in strategy_log


def test_demo_configuration_remains_dry_run_and_has_no_receipt():
    config = yaml.safe_load(
        (ROOT / "Config" / "config_demo.yaml").read_text(encoding="utf-8")
    )
    assert config["ccxt"]["mode"] == "dry_run"
    assert config["trade"]["strategy_receipt"] == ""
    assert config["ccxt"]["api_key"] == ""
    assert config["ccxt"]["secret"] == ""
