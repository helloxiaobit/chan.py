"""Independent processes keep the original native monetary SQLite chain."""
import copy
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from Common.ChanException import CChanException
from Common.NotificationStatus import read_notification_summary
from Trade.NativeOrderTransition import read_native_order_transition
from Trade import NativeOrderTransition as Transition
from .native_configured_process import export_raw_venue
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case
from .test_native_configured_entry import configure_cli, freeze_cli_epoch


ROOT = Path(__file__).resolve().parents[1]


def run_stage(case, raw, trace, root, module, **changes):
    stage = uuid4().hex
    report = root/(stage+".json")
    env = {**os.environ, "CHANPY_CYCLE_STAGE_ID": stage, "CHANPY_NOTIFICATION_REPORT": str(report), **changes}
    result = subprocess.run([sys.executable, "-m", "tests.native_configured_process", str(raw), str(trace), module],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    case["clock"]["now"] = json.loads(raw.read_text(encoding="utf-8"))["now_ms"]
    notice = read_notification_summary(report, run_id=env["CHANPY_CYCLE_ID"], stage_id=stage, module=module)
    assert notice["state"] == "complete", (result.returncode, result.stdout, result.stderr, notice)
    assert "I_ACCEPT_REAL_ORDERS" not in result.stdout+result.stderr
    assert "RuntimeWarning" not in result.stderr, result.stderr
    return result


def test_original_native_cli_restarts_without_reseeding_history_or_resubmitting(capacity_case, monkeypatch, tmp_path):
    case = capacity_case
    parent_posts, _ = configure_cli(case, monkeypatch)
    raw, trace = tmp_path/"raw-venue.json", tmp_path/"http.jsonl"
    export_raw_venue(case, raw)
    freeze_cli_epoch(case, monkeypatch)
    db = case["db"]
    prior = {key: (copy.deepcopy(db.get_record(key)), copy.deepcopy(db.get_order_history(key))) for key in case["history_keys"]}
    first = run_stage(case, raw, trace, tmp_path, "Trade.Script.MakeOpenTrade")
    assert first.returncode == 0, (first.stdout, first.stderr)
    record = db.get_record(case["key"])
    assert record["open_attempt"] == 1 and record["open_order_id"] == "123456"
    assert record["open_order_status"] == "open" and record["current_qty"] == 0
    claim = read_native_order_transition(db, case["key"])
    assert claim["payload"]["stage"] == "claim"
    assert claim["payload"]["root"]["preparation"]["schema"] == "chan-native-prepared-intent-binding-v4"
    history = db.get_order_history(case["key"])
    assert [event["kind"] for event in history["attempts"][0]["events"]][:4] == ["intent", "claim", "ack", "sdk_submission_report"]
    second = run_stage(case, raw, trace, tmp_path, "Trade.Script.MakeOpenTrade")
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert db.get_record(case["key"]) == record and db.get_order_history(case["key"]) == history
    assert read_native_order_transition(db, case["key"]) == claim
    assert {key: (db.get_record(key), db.get_order_history(key)) for key in prior} == prior

    # The approved query-only role needs none of the new-risk permission.
    config = json.loads(case["config"].read_bytes())
    del config["trade"]["native_admission"]
    del config["trade"]["strategy_receipt"]
    case["config"].write_text(json.dumps(config), encoding="utf-8")
    venue = json.loads(raw.read_text(encoding="utf-8"))
    venue.update(now_ms=case["clock"]["now"]+3_600_000, query_unavailable=True)
    raw.write_text(json.dumps(venue), encoding="utf-8")
    changes = {"CHANPY_KILL_SWITCH": "YES", "CHANPY_LIVE_TRADING_UNLOCK": ""}
    unavailable = run_stage(case, raw, trace, tmp_path, "Trade.Script.RestoreOrders", **changes)
    assert unavailable.returncode == 1 and "unresolved=1" in unavailable.stdout, (unavailable.stdout, unavailable.stderr)
    assert db.get_record(case["key"]) == record and db.get_order_history(case["key"]) == history
    assert read_native_order_transition(db, case["key"]) == claim
    venue = json.loads(raw.read_text(encoding="utf-8"))
    venue["query_unavailable"] = False
    raw.write_text(json.dumps(venue), encoding="utf-8")
    healthy = run_stage(case, raw, trace, tmp_path, "Trade.Script.RestoreOrders", **changes)
    assert healthy.returncode == 0 and "restored=2 unresolved=0" in healthy.stdout, (healthy.stdout, healthy.stderr)
    assert read_native_order_transition(db, case["key"]) == claim
    fields = ("status", "open_attempt", "open_order_id", "open_client_order_id", "open_order_contract",
              "open_order_status", "current_qty", "open_filled_qty", "open_price")
    for key, (previous, _) in {**prior, case["key"]: (record, history)}.items():
        current = db.get_record(key)
        assert {field: current[field] for field in fields} == {field: previous[field] for field in fields}
    for key, (_, previous) in {**prior, case["key"]: (record, history)}.items():
        current = db.get_order_history(key)
        assert len(current["attempts"]) == len(previous["attempts"])
        for before, after in zip(previous["attempts"], current["attempts"]):
            assert after["identity"] == before["identity"]
            assert after["events"][:len(before["events"])] == before["events"]
    # A query role skips no original proof checks and never repairs a bad L2.
    original_record = db.get_record(case["key"])
    proof = db.db.query_one("SELECT payload FROM chanpy_native_order_transitions WHERE record_id=? AND stage='claim'", (case["key"],))["payload"]
    damaged = proof+" "
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute("UPDATE chanpy_native_order_transitions SET payload=? WHERE record_id=? AND stage='claim'", (damaged, case["key"]))
    # Deliberate corruption of this temporary fake DB only, as in the existing
    # transition mutation tests. Restore the exact original guard before any
    # child/reader runs; bypassing the trigger must never be production logic.
    with db.db.transaction():
        trigger = Transition.TABLE+"_no_update"
        db.db.execute(f"DROP TRIGGER {trigger}")
        db.db.execute("UPDATE chanpy_native_order_transitions SET payload=? WHERE record_id=? AND stage='claim'", (damaged, case["key"]))
        db.db.execute(Transition.SCHEMA[trigger])
    invalid = run_stage(case, raw, trace, tmp_path, "Trade.Script.RestoreOrders", **changes)
    assert invalid.returncode == 1, (invalid.stdout, invalid.stderr)
    assert db.get_record(case["key"]) == original_record
    assert db.db.query_one("SELECT payload FROM chanpy_native_order_transitions WHERE record_id=? AND stage='claim'", (case["key"],))["payload"] == damaged
    with pytest.raises(CChanException):
        read_native_order_transition(db, case["key"])
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    boots = [row for row in rows if row["kind"] == "boot"]
    assert len(boots) == 5 and len({row["pid"] for row in boots}|{os.getpid()}) == 6
    assert all(row["preloaded"] is False for row in boots)
    expected_db = json.loads(case["config"].read_bytes())["db"]["sqlite_path"]
    assert {Path(row["database"]).resolve() for row in boots} == {Path(expected_db).resolve()}
    posts = [row for row in rows if row.get("method") == "POST"]
    assert len(posts) == 1 and posts[0]["pid"] == boots[0]["pid"]
    assert posts[0]["params"]["newClientOrderId"] == record["open_client_order_id"]
    assert posts[0]["params"]["positionSide"] == record["position_side"]
    assert posts[0]["params"]["side"] == ("BUY" if record["is_buy"] else "SELL")
    assert not parent_posts, "the seeding parent must not submit the new native intent"
    assert "signature" not in trace.read_text(encoding="utf-8")
    assert not any(row["kind"] == "network_escape_blocked" for row in rows)
