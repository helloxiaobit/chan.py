import json
import pickle
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["trades"]
    assert "候选迁移通过" in completed.stdout
