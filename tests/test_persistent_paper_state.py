"""纸面服务器必须在全新对象/进程恢复，不借用原内存句柄。"""
import json
import copy
import hashlib
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_linear_paper_account import paper_account, quote, filled, CODE
from .test_linear_paper_engine import paper_engine
from .test_execution_store import store
from .test_m6_trade import make_signal


ROOT = Path(__file__).resolve().parents[1]
WORKER = r'''
import os, sys
from Trade.PaperState import CPersistentPaperState
from Trade.db_util import CChanDB
from tests.test_linear_paper_account import paper_account, CODE
from tests.test_linear_paper_engine import paper_engine
from tests.test_m6_trade import make_signal
server_path, db_path, phase = sys.argv[1:]
db = CChanDB(db_conf={"type":"sqlite", "sqlite_path":db_path})
with CPersistentPaperState.create(server_path, account=paper_account(mode="one_way"), database=db_path) as server:
    engine = paper_engine(db, state=server.state)
    engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
    record = db.get_record(db.add_signal(make_signal(code=CODE)))
    client = engine.make_client_order_id(record, "open")
    engine.set_sim_fill_plan(client, [0.01, 0.01, 0.03])
    if phase == "before_intent":
        os._exit(73)
    if phase == "after_intent":
        original = db.acquire_open_intent
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(73)
        db.acquire_open_intent = crash
    if phase == "accepted_no_ack":
        db.record_order_ack = lambda *a, **k: os._exit(73)
    engine.add_trade(record, 102)
    if phase == "partial":
        os._exit(73)
    if phase == "cancel_no_confirmation":
        engine.cancel_order(CODE, db.get_record(record["id"])["open_order_id"])
        os._exit(73)
raise AssertionError("fault point was not reached")
'''


def test_actual_account_restorer_replays_all_effects_and_preserves_idempotency():
    from Trade.LinearPaperAccount import restore_linear_paper_account
    account = paper_account(mode="one_way")
    quote(account, 1001)
    filled(account, "first", "r1", 1001, leg="BOTH", quantity="0.03")
    before = account.to_dict()
    rebuilt = restore_linear_paper_account(before)
    assert rebuilt is not account and canonical_bytes(rebuilt.to_dict()) == canonical_bytes(before)
    filled(rebuilt, "first", "r1", 1001, leg="BOTH", quantity="0.03")
    assert rebuilt.to_dict() == before
    before["account"]["snapshot"]["cash"] = "9999999"
    with pytest.raises(CChanException):
        restore_linear_paper_account(before)


def test_new_server_instance_loads_original_partial_order_not_a_new_simulation(store, tmp_path):
    from Trade.PaperState import CPersistentPaperState
    db, conf = store
    path = tmp_path/"paper-server.json"
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        client = engine.make_client_order_id(record, "open")
        engine.set_sim_fill_plan(client, [0.01, 0.03])
        result = engine.add_trade(record, 102)
        assert result.filled == 0.01
        before = engine.get_sim_account_report()
        contract = json.loads(db.get_record(record["id"])["open_order_contract"])
        assert contract["schema"] == "chan-paper-order-v2" and contract["paper_store"] == server.reference
        first_state = server.state
    with CPersistentPaperState.open(path, database=conf["sqlite_path"]) as server:
        assert server.state is not first_state
        engine = paper_engine(db, state=server.state)
        assert engine.get_sim_account_report() == before
        engine.set_sim_quote(CODE, at_ms=1002, bid="100.9", ask="101", mark_price="101")
        engine.restore()
        assert db.get_record(record["id"])["current_qty"] == 0.03
        assert len(server.state.orders) == 1
        after = engine.get_sim_account_report()
        engine.restore()
        assert engine.get_sim_account_report() == after
        assert engine.exchange is None


def test_open_never_creates_missing_or_replaces_existing_or_damaged_server(store, tmp_path):
    from Trade.PaperState import CPersistentPaperState
    _, conf = store
    path = tmp_path/"paper-server.json"
    with pytest.raises(CChanException):
        CPersistentPaperState.open(path, database=conf["sqlite_path"])
    assert not path.exists()
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]):
        original = path.read_bytes()
    with pytest.raises(CChanException):
        CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"])
    assert path.read_bytes() == original
    path.write_bytes(b"partial-json")
    with pytest.raises(CChanException):
        CPersistentPaperState.open(path, database=conf["sqlite_path"])
    assert path.read_bytes() == b"partial-json"


@pytest.mark.parametrize("phase", ["before_intent", "after_intent", "accepted_no_ack", "partial", "cancel_no_confirmation"])
def test_actual_process_exit_recovers_original_server_without_duplicate_order_or_fee(store, tmp_path, phase):
    db, conf = store
    path = tmp_path/"paper-server.json"
    result = subprocess.run([sys.executable, "-c", WORKER, str(path), conf["sqlite_path"], phase],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stdout+result.stderr
    # A new reader/engine has no shared server object, and the dead writer's
    # OS lock must actually be released rather than inferred from a lock file.
    from Trade.PaperState import CPersistentPaperState
    with CPersistentPaperState.open(path, database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.restore()
        current = db.get_record(1)
        if phase in {"before_intent", "after_intent"}:
            assert current["current_qty"] == 0 and server.state.orders == {}
            assert current["open_attempt"] == (0 if phase == "before_intent" else 1)
            assert engine.get_sim_account_report()["account"]["snapshot"]["fees"] == "0"
        else:
            assert current["current_qty"] == 0.01 and len(server.state.orders) == 1
            assert current["open_order_status"] == ("canceled" if phase == "cancel_no_confirmation" else "open")
            assert engine.get_sim_account_report()["account"]["snapshot"]["fees"] == "0.001001"
            if phase != "cancel_no_confirmation":
                engine.set_sim_quote(CODE, at_ms=1002, bid="100.9", ask="101", mark_price="101")
                engine.restore()
                assert db.get_record(1)["current_qty"] == 0.03
                before = engine.get_sim_account_report()
                engine.restore()
                assert engine.get_sim_account_report() == before
            engine.set_sim_quote(CODE, at_ms=1003, bid="110", ask="110.1", mark_price="110")
            engine.cover_trade(db.get_record(1), None, "reduce recovered position")
            assert db.get_record(1)["current_qty"] == 0
            assert len(server.state.orders) == 2
        assert engine.exchange is None


@pytest.mark.parametrize("replace_happened", [False, True])
def test_checkpoint_failure_never_acknowledges_volatile_server_state_or_resubmits(store, tmp_path, monkeypatch, replace_happened):
    from Trade.PaperState import CPersistentPaperState
    from Trade import PaperState as module
    db, conf = store
    path = tmp_path/"paper-server.json"
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        replace = module.os.replace
        def unavailable(source, destination):
            if replace_happened:
                replace(source, destination)
            raise OSError("private-transport-text must not escape")
        monkeypatch.setattr(module.os, "replace", unavailable)
        with pytest.raises(CChanException) as error:
            engine.add_trade(record, 102)
        assert "private-transport-text" not in str(error.value)
        assert db.get_record(record["id"])["open_order_status"] == "submitting"
        assert db.get_record(record["id"])["open_order_id"] is None
        with pytest.raises(CChanException):
            engine.get_sim_account_report()
        monkeypatch.setattr(module.os, "replace", replace)
    with CPersistentPaperState.open(path, database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.restore()
        assert len(server.state.orders) == (1 if replace_happened else 0)
        assert db.get_record(record["id"])["current_qty"] == (0.03 if replace_happened else 0)


@pytest.mark.parametrize("damage", ["cash", "filled", "average", "cursor_rewind", "cursor_overrun", "plan",
    "role", "duplicate", "counter", "store", "unknown", "orphan_fill"])
def test_resealed_checkpoint_still_needs_actual_effects_order_and_cursor_agreement(store, tmp_path, damage):
    from Trade.PaperState import CPersistentPaperState
    from Trade.LinearPaperAccount import restore_linear_paper_account
    db, conf = store
    path = tmp_path/"paper-server.json"
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
        engine.add_trade(record, 102)
    document = json.loads(path.read_bytes())
    state = document["payload"]["state"]
    order = state["orders"][0]
    if damage == "cash":
        state["account"]["account"]["snapshot"]["cash"] = "99999"
    elif damage == "filled":
        order["result"]["filled"] = 0.02
    elif damage == "average":
        order["result"]["avg_price"] += 1
    elif damage == "cursor_rewind":
        order["next_fill"] = 0
    elif damage == "cursor_overrun":
        order["next_fill"] = 100
    elif damage == "plan":
        order["fill_plan"][-1] = 0.04
    elif damage == "role":
        order["paper_role"] = "maker"
    elif damage == "duplicate":
        state["orders"].append(copy.deepcopy(order))
    elif damage == "counter":
        state["next_order_sequence"] = 1
    elif damage == "store":
        contract = order["paper_contract"]
        contract["paper_store"]["store_id"] = "0"*32
        contract["contract_id"] = hashlib.sha256(canonical_bytes({k:v for k,v in contract.items() if k != "contract_id"})).hexdigest()
    elif damage == "unknown":
        order["ready"] = True
    else:
        account = restore_linear_paper_account(state["account"])
        account.execute_fill(execution_id="orphan", position_id="chan_trade:999", code=CODE, is_buy=True,
            quantity="0.01", execution_price="100.1", position_side="BOTH", reduce_only=False, role="taker", at_ms=1001)
        state["account"] = account.to_dict()  # valid financial replay, but no server order owns it
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(CChanException):
        CPersistentPaperState.open(path, database=conf["sqlite_path"])


def test_known_local_ack_cannot_be_reconciled_against_an_older_empty_server_checkpoint(store, tmp_path):
    from Trade.PaperState import CPersistentPaperState
    db, conf = store
    path = tmp_path/"paper-server.json"
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
        old = path.read_bytes()
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.add_trade(record, 102)
        engine.set_sim_quote(CODE, at_ms=1002, bid="110", ask="110.1", mark_price="110")
        engine.cover_trade(db.get_record(record["id"]), None, "close")
        assert db.get_record(record["id"])["current_qty"] == 0
    path.write_bytes(old)
    with pytest.raises(CChanException):
        with CPersistentPaperState.open(path, database=conf["sqlite_path"]) as server:
            paper_engine(db, state=server.state)


def test_real_second_process_cannot_claim_live_server_but_can_open_after_owner_exits(store, tmp_path):
    from Trade.PaperState import CPersistentPaperState
    _, conf = store
    path = tmp_path/"paper-server.json"
    child = r'''
import sys
from Common.ChanException import CChanException
from Trade.PaperState import CPersistentPaperState
try:
    with CPersistentPaperState.open(sys.argv[1], database=sys.argv[2]):
        pass
except CChanException:
    sys.exit(7)
'''
    def run():
        return subprocess.run([sys.executable, "-c", child, str(path), conf["sqlite_path"]], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]):
        result = run()
        assert result.returncode == 7, result.stdout+result.stderr
    assert run().returncode == 0


@pytest.mark.parametrize("change", ["database", "server_path", "runtime", "live_bytes", "live_memory", "missing"])
def test_bound_server_never_adopts_a_different_identity_or_live_state(store, tmp_path, monkeypatch, change):
    from Trade.PaperState import CPersistentPaperState
    from Trade import PaperState as module
    from Trade.db_util import CChanDB
    db, conf = store
    path = tmp_path/"paper-server.json"
    with CPersistentPaperState.create(path, account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        if change in {"live_bytes", "live_memory", "missing"}:
            engine = paper_engine(db, state=server.state)
            if change == "live_bytes":
                path.write_bytes(path.read_bytes()+b"\n")
            elif change == "missing":
                path.unlink()
            else:
                server.state.paper_account.set_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
            with pytest.raises(CChanException):
                engine.get_sim_account_report()
            return
    if change == "server_path":
        clone = tmp_path/"clone.json"
        clone.write_bytes(path.read_bytes())
        path = clone
    if change == "runtime":
        runtime = {**module._runtime(), "python": "unverified-runtime"}
        monkeypatch.setattr(module, "_runtime", lambda: runtime)
    other = None
    try:
        database = conf["sqlite_path"]
        if change == "database":
            database = str(tmp_path/"other.db")
            other = CChanDB(db_conf={"type": "sqlite", "sqlite_path": database})
        with pytest.raises(CChanException):
            CPersistentPaperState.open(path, database=database)
    finally:
        if other is not None:
            other.close()


def test_close_cannot_release_the_os_writer_lock_during_an_active_operation(store, tmp_path):
    from Trade.PaperState import CPersistentPaperState
    _, conf = store
    entered, release, failures = threading.Event(), threading.Event(), []
    with CPersistentPaperState.create(tmp_path/"paper-server.json", account=paper_account(mode="one_way"), database=conf["sqlite_path"]) as server:
        def writer():
            try:
                with server.operation(server.state):
                    entered.set()
                    assert release.wait(5)
            except BaseException as error:
                failures.append(error)
        thread = threading.Thread(target=writer)
        thread.start()
        try:
            assert entered.wait(5)
            with pytest.raises(CChanException):
                server.close()
            with pytest.raises(CChanException):
                CPersistentPaperState.open(server.path, database=conf["sqlite_path"])
        finally:
            release.set()
            thread.join(10)
        assert not thread.is_alive() and failures == []
