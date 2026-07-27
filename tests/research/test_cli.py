import json
import pickle
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ModelStrategy.research.baseline import run_baseline
from ModelStrategy.research.conservative_baseline import (
    conservative_reference_payload,
    run_conservative_comparison,
)
from ModelStrategy.research.boundary import parse_utc
from tests.research.test_baseline import make_spec, write_fixture_inputs
from tests.research.test_conservative_baseline import make_conservative_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]


def prepare_fixture(tmp_path):
    spec = make_spec(tmp_path)
    write_fixture_inputs(tmp_path)
    report = run_baseline(
        spec,
        research_root=tmp_path,
        provenance={"commit": "test", "dirty": False},
    )
    reference = {
        "schema_version": report["schema_version"],
        "strategy_id": report["strategy_id"],
        "execution_model": report["execution_model"],
        **report["result"],
    }
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    return tmp_path / "spec.json", reference_path


def run_cli(tmp_path, spec_path, reference_path, output_path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ModelStrategy.research.cli",
            "baseline",
            "--spec",
            str(spec_path),
            "--research-root",
            str(tmp_path),
            "--reference",
            str(reference_path),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_writes_baseline_report_atomically(tmp_path):
    spec_path, reference_path = prepare_fixture(tmp_path)
    output_path = tmp_path / "output" / "report.json"
    completed = run_cli(tmp_path, spec_path, reference_path, output_path)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["result"]["risk_pct"] == 0.01
    assert "基线复现通过" in completed.stdout


def test_cli_reference_mismatch_leaves_no_output(tmp_path):
    spec_path, reference_path = prepare_fixture(tmp_path)
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["risk_pct"] = 0.123
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    output_path = tmp_path / "output" / "report.json"
    completed = run_cli(tmp_path, spec_path, reference_path, output_path)
    assert completed.returncode != 0
    assert "risk_pct" in completed.stderr
    assert not output_path.exists()
    assert not list(output_path.parent.glob("*.tmp"))


def test_cli_rejects_oos_spec_before_data_loading(tmp_path):
    spec = make_spec(tmp_path)
    raw = spec.raw
    raw["window"]["end_exclusive"] = "2026-01-02"
    spec_path = tmp_path / "oos-spec.json"
    spec_path.write_text(json.dumps(raw), encoding="utf-8")
    missing_reference = tmp_path / "missing-reference.json"
    output_path = tmp_path / "report.json"
    completed = run_cli(
        tmp_path, spec_path, missing_reference, output_path
    )
    assert completed.returncode != 0
    assert "2026-01-01" in completed.stderr
    assert not output_path.exists()


def run_compare_cli(
    tmp_path,
    spec_path,
    legacy_reference_path,
    output_path,
    conservative_reference_path=None,
):
    command = [
        sys.executable,
        "-m",
        "ModelStrategy.research.cli",
        "compare",
        "--spec",
        str(spec_path),
        "--research-root",
        str(tmp_path),
        "--market-data-root",
        str(tmp_path),
        "--legacy-reference",
        str(legacy_reference_path),
        "--output",
        str(output_path),
    ]
    if conservative_reference_path is not None:
        command.extend(
            ["--conservative-reference", str(conservative_reference_path)]
        )
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_compare_cli_writes_report_atomically(tmp_path):
    spec_path, legacy_path, _ = make_conservative_fixture(tmp_path)
    output_path = tmp_path / "output" / "comparison.json"
    completed = run_compare_cli(
        tmp_path, spec_path, legacy_path, output_path
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["execution_model"] == "conservative-v2"
    assert "保守回测通过" in completed.stdout


def test_compare_cli_reference_mismatch_leaves_no_output(tmp_path):
    spec_path, legacy_path, legacy_reference = make_conservative_fixture(tmp_path)
    report = run_conservative_comparison(
        spec_path,
        research_root=tmp_path,
        market_data_root=tmp_path,
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    reference = conservative_reference_payload(report)
    reference["risk_pct"] = 0.123
    reference_path = tmp_path / "conservative-reference.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    output_path = tmp_path / "output" / "comparison.json"
    completed = run_compare_cli(
        tmp_path,
        spec_path,
        legacy_path,
        output_path,
        conservative_reference_path=reference_path,
    )
    assert completed.returncode != 0
    assert "risk_pct" in completed.stderr
    assert not output_path.exists()
    assert not list(output_path.parent.glob("*.tmp"))


def test_migrate_candidate_cli_writes_guarded_json(tmp_path):
    source = tmp_path / "trusted-is-cache.pkl"
    with source.open("wb") as stream:
        pickle.dump(
            [
                SimpleNamespace(
                    code="BTC/USDT",
                    open_ts=parse_utc("2021-02-01"),
                    close_ts=parse_utc("2021-02-02"),
                    open_price=100.0,
                    close_price=105.0,
                    risk_rate=0.05,
                    bs_type="z1",
                    is_buy=True,
                    is_pyramid=False,
                    reason="trend_flip",
                    is_closed=True,
                )
            ],
            stream,
        )
    output = tmp_path / "normalized" / "candidate.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ModelStrategy.research.cli",
            "migrate-candidate",
            "--input-pickle",
            str(source),
            "--output",
            str(output),
            "--symbol",
            "BTC/USDT",
            "--stack",
            "S1bz[4H,1H,15M]",
            "--entry-kind",
            "strategy_fill",
            "--begin",
            "2021-01-01",
            "--end-exclusive",
            "2026-01-01",
            "--timestamp-offset-seconds",
            "0",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["trades"]
    assert "候选迁移通过" in completed.stdout


def fake_candidate_report():
    return {
        "schema_version": 1,
        "strategy_id": "freeze_v5_candidate_v1",
        "execution_model": "conservative-v2",
        "status": "rejected",
        "stop_reason": "btc_full_calmar",
        "spec_hash": "a" * 64,
        "selected_risk_pct": 0.005,
        "btc": {"cagr": 0.3, "full_dd": 0.2, "calmar": 1.5},
        "gates": [{"name": "btc_full_calmar", "passed": False}],
        "execution": {"filled": 1},
        "input_hashes": {"s1_trades": "b" * 64},
        "unopened_tiers": ["ETH/USDT", "SOL/USDT", "BNB/USDT", "OOS"],
    }


def candidate_cli_args(tmp_path, output):
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    freeze_v4 = tmp_path / "freeze-v4.json"
    freeze_v4.write_text("{}", encoding="utf-8")
    return [
        "certify-v5-btc-is",
        "--spec",
        str(spec),
        "--research-root",
        str(tmp_path),
        "--market-data-root",
        str(tmp_path),
        "--freeze-v4-reference",
        str(freeze_v4),
        "--output",
        str(output),
    ]


def test_candidate_cli_writes_atomic_is_report(monkeypatch, tmp_path):
    from ModelStrategy.research import certification, cli

    monkeypatch.setattr(
        certification,
        "run_btc_is_certification",
        lambda *args, **kwargs: fake_candidate_report(),
    )
    output = tmp_path / "output" / "candidate.json"
    assert cli.main(candidate_cli_args(tmp_path, output)) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "rejected"
    assert not list(output.parent.glob("*.tmp"))


def test_candidate_cli_reference_mismatch_leaves_no_output(
    monkeypatch, tmp_path
):
    from ModelStrategy.research import certification, cli

    report = fake_candidate_report()
    monkeypatch.setattr(
        certification,
        "run_btc_is_certification",
        lambda *args, **kwargs: report,
    )
    reference = certification.certification_reference_payload(report)
    reference["selected_risk_pct"] = 0.01
    reference_path = tmp_path / "candidate-reference.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    output = tmp_path / "output" / "candidate.json"
    args = candidate_cli_args(tmp_path, output)
    args[args.index("--output"):args.index("--output")] = [
        "--candidate-reference",
        str(reference_path),
    ]
    assert cli.main(args) == 2
    assert not output.exists()
    assert not output.parent.exists() or not list(output.parent.glob("*.tmp"))


def test_candidate_cli_empty_reference_cannot_bypass_freeze(
    monkeypatch, tmp_path
):
    from ModelStrategy.research import certification, cli

    monkeypatch.setattr(
        certification,
        "run_btc_is_certification",
        lambda *args, **kwargs: fake_candidate_report(),
    )
    reference_path = tmp_path / "empty-reference.json"
    reference_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output" / "candidate.json"
    args = candidate_cli_args(tmp_path, output)
    args[args.index("--output"):args.index("--output")] = [
        "--candidate-reference",
        str(reference_path),
    ]
    assert cli.main(args) == 2
    assert not output.exists()


def test_candidate_is_cli_has_no_oos_capable_argument(tmp_path):
    from ModelStrategy.research import cli

    args = candidate_cli_args(tmp_path, tmp_path / "candidate.json")
    args.extend(["--oos-input", str(tmp_path / "sealed.json")])
    with pytest.raises(SystemExit):
        cli.main(args)
