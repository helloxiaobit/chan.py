"""Canonical bounded stage summaries; raw child output is never the evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from Common import send_msg_cmd as notify
from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_notification_observation import configure, SECRET


RUN = "1"*32
STAGE = "2"*32
MODULE = "Trade.Script.SignalMonitor"
ROOT = Path(__file__).resolve().parents[1]


def test_notification_summary_is_canonical_write_once_and_identity_bound(configure, tmp_path):
    from Common.NotificationStatus import observe_notifications, publish_notification_summary, read_notification_summary
    configure("none")
    with observe_notifications() as summary:
        notify.send_msg("private title", "private body")
    path = tmp_path/"observation.json"
    publish_notification_summary(path, summary, run_id=RUN, stage_id=STAGE, module=MODULE)
    raw = path.read_bytes()
    assert raw == canonical_bytes(json.loads(raw)) and b"private" not in raw
    result = read_notification_summary(path, run_id=RUN, stage_id=STAGE, module=MODULE)
    assert result == {"state": "complete", "counts": summary.snapshot()}
    with pytest.raises(CChanException):
        publish_notification_summary(path, summary, run_id=RUN, stage_id=STAGE, module=MODULE)
    assert path.read_bytes() == raw
    assert read_notification_summary(path, run_id="3"*32, stage_id=STAGE, module=MODULE) == {"state": "unavailable", "counts": None}


@pytest.mark.parametrize("damage", ["backend", "extra", "count", "complete", "hash", "bytes", "oversize"])
def test_malformed_summaries_are_unknown_not_zero_failure(configure, tmp_path, damage):
    from Common.NotificationStatus import observe_notifications, publish_notification_summary, read_notification_summary
    configure("none")
    with observe_notifications() as summary:
        notify.send_msg("synthetic title", "synthetic body")
    path = tmp_path/"observation.json"
    publish_notification_summary(path, summary, run_id=RUN, stage_id=STAGE, module=MODULE)
    doc = json.loads(path.read_bytes())
    payload = doc["payload"]
    if damage == "backend":
        payload["counts"][0]["backend"] = SECRET
    elif damage == "extra":
        payload["message"] = SECRET
    elif damage == "count":
        payload["counts"][0]["failed"] = True
    elif damage == "complete":
        payload["counts"][0]["attempted"] = 2
    doc["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    if damage == "hash":
        doc["payload_sha256"] = "0"*64
    raw = json.dumps(doc, indent=2).encode() if damage == "bytes" else canonical_bytes(doc)
    path.write_bytes(raw if damage != "oversize" else b" "*20_000)
    assert read_notification_summary(path, run_id=RUN, stage_id=STAGE, module=MODULE) == {"state": "unavailable", "counts": None}


def test_interrupted_attempt_stays_incomplete_even_if_the_stage_can_publish(configure, monkeypatch, tmp_path):
    import requests
    from Common.NotificationStatus import observe_notifications, publish_notification_summary, read_notification_summary
    configure("telegram")
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(requests, "post", interrupt)
    with observe_notifications() as summary:
        with pytest.raises(KeyboardInterrupt):
            notify.send_msg("synthetic title", "synthetic body")
    path = tmp_path/"interrupted.json"
    publish_notification_summary(path, summary, run_id=RUN, stage_id=STAGE, module=MODULE)
    assert read_notification_summary(path, run_id=RUN, stage_id=STAGE, module=MODULE) == {"state": "incomplete", "counts": summary.snapshot()}


def test_real_fresh_stage_process_can_prove_zero_notifications_instead_of_missing_summary(configure, tmp_path):
    from Common.NotificationStatus import read_notification_summary
    configure("none")
    path = tmp_path/"child.json"
    module = "Trade.Script.RestoreOrders"
    result = subprocess.run([sys.executable, "-m", "Trade.Script.RunTradeStage", module], cwd=ROOT,
        env={**os.environ, "CHANPY_CYCLE_ID": RUN, "CHANPY_CYCLE_STAGE_ID": STAGE, "CHANPY_NOTIFICATION_REPORT": str(path)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
    assert read_notification_summary(path, run_id=RUN, stage_id=STAGE, module=module) == {"state": "complete", "counts": []}


def test_stage_exception_is_redacted_and_does_not_lose_the_notification_attempt(configure, tmp_path, monkeypatch, capsys):
    from Trade.Script import RunTradeStage as stage
    from Common.NotificationStatus import read_notification_summary
    import requests
    configure("telegram")
    path = tmp_path/"failed-child.json"
    monkeypatch.setenv("CHANPY_CYCLE_ID", RUN)
    monkeypatch.setenv("CHANPY_CYCLE_STAGE_ID", STAGE)
    monkeypatch.setenv("CHANPY_NOTIFICATION_REPORT", str(path))
    monkeypatch.setattr(sys, "argv", ["RunTradeStage", MODULE])
    def execute(*args, **kwargs):
        assert notify.send_msg("synthetic title", "synthetic body") is False
        raise RuntimeError(SECRET)
    monkeypatch.setattr(requests, "post", lambda *a, **k: type("Response", (), {"status_code": 503})())
    monkeypatch.setattr(stage.runpy, "run_module", execute)
    assert stage.main() == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err and "Traceback" not in captured.out+captured.err
    assert read_notification_summary(path, run_id=RUN, stage_id=STAGE, module=MODULE)["counts"][0]["failed"] == 1


def test_stage_cannot_execute_an_arbitrary_module(configure, tmp_path):
    configure("none")
    path = tmp_path/"forbidden.json"
    result = subprocess.run([sys.executable, "-m", "Trade.Script.RunTradeStage", SECRET], cwd=ROOT,
        env={**os.environ, "CHANPY_CYCLE_ID": RUN, "CHANPY_CYCLE_STAGE_ID": STAGE, "CHANPY_NOTIFICATION_REPORT": str(path)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and SECRET not in result.stdout+result.stderr and not path.exists()


@pytest.mark.parametrize("code", [0, 37])
@pytest.mark.parametrize("broken_stderr", [False, True])
def test_summary_publication_or_diagnostic_failure_preserves_original_exit(configure, tmp_path, monkeypatch, code, broken_stderr):
    from Trade.Script import RunTradeStage as stage
    configure("none")
    path = tmp_path/"existing.json"
    path.write_bytes(b"original observation")
    monkeypatch.setenv("CHANPY_CYCLE_ID", RUN)
    monkeypatch.setenv("CHANPY_CYCLE_STAGE_ID", STAGE)
    monkeypatch.setenv("CHANPY_NOTIFICATION_REPORT", str(path))
    monkeypatch.setattr(sys, "argv", ["RunTradeStage", MODULE])
    def execute(*args, **kwargs):
        raise SystemExit(code)
    monkeypatch.setattr(stage.runpy, "run_module", execute)
    if broken_stderr:
        def failed_diagnostic(*args, **kwargs):
            raise BrokenPipeError(SECRET)
        monkeypatch.setattr(stage, "print", failed_diagnostic, raising=False)
    assert stage.main() == code
    assert path.read_bytes() == b"original observation"
