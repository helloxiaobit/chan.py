"""The public offline rehearsal uses actual data/strategy/model and child processes."""
import json
import os
import hashlib
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes


def test_actual_no_network_rehearsal_closes_original_orders_across_fresh_processes(tmp_path):
    from Trade.Script.PaperRehearsal import run_paper_rehearsal
    output = tmp_path/"new-rehearsal"
    report = run_paper_rehearsal(output)
    assert report["schema"] == "chan-offline-paper-rehearsal-v1"
    assert report["status"] == "completed" and report["synthetic_only"] is True
    assert report["candidate_authorized"] is False and report["exchange_certified"] is False
    assert report["rows"] == 1000 and report["training_rows"] == 600 and report["boost_rounds"] == 2
    assert report["decision_reconciled"] is True and report["event_ledger_reconciled"] is True
    assert len(set(report["worker_pids"])) == 3 and os.getpid() not in report["worker_pids"]
    stages = [json.loads((output/f"{phase}.json").read_bytes()) for phase in ("entry", "exit", "verify")]
    assert [stage["current_qty"] for stage in stages] == [0.01, 0.02, 0]
    assert [stage["order_count"] for stage in stages] == [1, 2, 2]
    assert all(stage["model_artifact_id"] == report["model_artifact_id"] for stage in stages)
    assert all(stage["deployment_id"] == report["deployment_id"] for stage in stages)
    for left, right in zip(stages, stages[1:]):
        old = left["account"]["effects"]
        assert canonical_bytes(old) == canonical_bytes(right["account"]["effects"][:len(old)])
    final = stages[-1]["account"]
    assert Decimal(final["account"]["snapshot"]["fees"]) > 0
    assert Decimal(final["account"]["snapshot"]["funding_pnl"]) != 0
    assert len([effect for effect in final["effects"] if effect["request"]["kind"] == "funding"]) == 1
    assert (output/"rehearsal.json").read_bytes() == canonical_bytes(report)
    before = (output/"rehearsal.json").read_bytes()
    with pytest.raises(CChanException):
        run_paper_rehearsal(output)
    assert (output/"rehearsal.json").read_bytes() == before


def test_existing_nonempty_destination_is_never_adopted_or_erased(tmp_path):
    from Trade.Script.PaperRehearsal import run_paper_rehearsal
    marker = tmp_path/"user.txt"
    marker.write_bytes(b"keep existing work")
    with pytest.raises(CChanException):
        run_paper_rehearsal(tmp_path)
    assert list(tmp_path.iterdir()) == [marker] and marker.read_bytes() == b"keep existing work"


@pytest.mark.parametrize("damage", ["model", "resealed_configuration"])
def test_real_child_rejects_drift_without_order_or_completion_receipt(tmp_path, monkeypatch, damage):
    from Trade.Script import PaperRehearsal as module
    from Trade.db_util import CChanDB
    output = tmp_path/"failed-rehearsal"
    original = module.subprocess.run
    calls = []
    def child(*args, **kwargs):
        calls.append(args[0])
        if damage == "model":
            deployment = json.loads((output/"deployment.json").read_bytes())
            model = (output/deployment["model_path"]).resolve()
            model.write_bytes(model.read_bytes()+b"private-error-detail")
        else:
            config = json.loads((output/"runtime.json").read_bytes())
            config["notify"]["extra_secret"] = "private-error-detail"
            (output/"runtime.json").write_bytes(canonical_bytes(config))
            scenario = json.loads((output/"scenario.json").read_bytes())
            scenario["config_sha256"] = hashlib.sha256((output/"runtime.json").read_bytes()).hexdigest()
            (output/"scenario.json").write_bytes(canonical_bytes(scenario))
        return original(*args, **kwargs)  # actual fresh worker, not a mocked success/failure result
    monkeypatch.setattr(module.subprocess, "run", child)
    with pytest.raises(CChanException) as error:
        module.run_paper_rehearsal(output)
    assert "private-error-detail" not in str(error.value)
    assert len(calls) == 1 and not (output/"rehearsal.json").exists()
    assert not (output/"entry.json").exists() and not (output/"server.json").exists()
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(output/"trade.db")})
    try:
        record = db.get_record(1)
        assert record["open_attempt"] == 0 and record["current_qty"] == 0
    finally:
        db.close()


def test_cli_refuses_existing_directory_with_nonzero_exit_and_preserves_bytes(tmp_path):
    marker = tmp_path/"original.txt"
    marker.write_bytes(b"original")
    result = subprocess.run([sys.executable, "-m", "Trade.Script.PaperRehearsal", "--output", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "no completion receipt" in result.stderr
    assert list(tmp_path.iterdir()) == [marker] and marker.read_bytes() == b"original"
