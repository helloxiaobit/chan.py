"""Exact original persisted L0, not a transferable order/funding permission."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_current_components import current_case
from .test_m6_trade import make_signal


def boundary_api():
    assert importlib.util.find_spec("Trade.NativeOrderBoundary") is not None, "original native order L0 boundary is missing"
    from Trade import NativeOrderBoundary
    return NativeOrderBoundary


def test_native_order_boundary_api_exists():
    api = boundary_api()
    assert callable(api.capture_native_order_boundary)
    assert callable(api.assert_native_order_boundary)


@pytest.fixture(params=[(venue, mode, side) for venue in ("binance", "okx") for mode in ("one_way", "hedged") for side in (True, False)])
def boundary_case(request, store, tmp_path, monkeypatch):
    api = boundary_api()
    db, conf = store
    venue, mode, side = request.param
    case = current_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    monkeypatch.setattr(api, "utc_now_ms", lambda: case["clock"]["now"])
    return {**case, "api": api, "conf": conf}


def capture(case):
    keys = ("account_context", "check_id", "market_evidence", "policy")
    return case["api"].capture_native_order_boundary(case["db"], **{key: case["arguments"][key] for key in keys})


def test_exact_nonempty_original_ledger_reopens_and_asserts_inside_real_sqlite_transaction(boundary_case):
    case = boundary_case
    db = case["db"]
    changes, orders = db.db.conn.total_changes, len(case["trade"].exchange.created)
    boundary = capture(case)
    assert boundary["schema"] == "chan-native-order-boundary-v1"
    payload = boundary["payload"]
    assert boundary["payload_sha256"] == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert payload["coverage"] == "exact_native_component_l0_only"
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    assert payload["check_id"] == case["arguments"]["check_id"]
    assert payload["journal_prefix"] == case["check"]["payload"]["inputs"]["journal_prefix"]
    assert payload["journal_prefix"]["attempt_count"] >= 3
    assert len(case["inputs"]["after"]["payload"]["positions"]) == 2
    assert len(case["params"]["pending_orders"]["payload"]["orders"]) == 1
    with db.db.transaction():
        assert case["api"].assert_native_order_boundary(db, boundary) is None
    restarted = CChanDB(db_conf=case["conf"])
    try:
        with restarted.db.transaction():
            assert case["api"].assert_native_order_boundary(restarted, boundary) is None
    finally:
        restarted.close()
    assert db.db.conn.total_changes == changes and len(case["trade"].exchange.created) == orders


def test_assertion_never_runs_without_original_transaction_ownership(boundary_case):
    case = boundary_case
    boundary = capture(case)
    with pytest.raises(CChanException):
        case["api"].assert_native_order_boundary(case["db"], boundary)
    connection = case["db"].db.conn
    connection.execute("BEGIN")
    try:
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(case["db"], boundary)
    finally:
        connection.rollback()


@pytest.mark.parametrize("field", ["ledger_sha256", "database_location_sha256", "check_id", "economics_complete", "native_admission_verified"])
def test_resealed_baseline_is_not_permission_to_replace_original_inputs(boundary_case, field):
    case = boundary_case
    boundary = copy.deepcopy(capture(case))
    boundary["payload"][field] = True if field in {"economics_complete", "native_admission_verified"} else "0"*64
    boundary["payload_sha256"] = hashlib.sha256(canonical_bytes(boundary["payload"])).hexdigest()
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(case["db"], boundary)


@pytest.mark.parametrize("other_table", [False, True])
def test_same_l0_serializes_real_cas_across_records_markets_and_connections(boundary_case, other_table):
    case = boundary_case
    db = case["db"]
    other = CChanDB(db_conf=case["conf"], table_name="other_signals" if other_table else db.table)
    first_code, second_code = "TEST/USDT:USDT", "ALT/USDT:USDT"
    try:
        first_key = db.add_signal(make_signal(code=first_code, is_buy=False))
        second_key = other.add_signal(make_signal(code=second_code, is_buy=False))
        first_qty, _, first_contract = case["trade"].prepare_order(first_code, 0.03, 100, record=db.get_record(first_key))
        second_qty, _, second_contract = case["trade"].prepare_order(second_code, 0.3, 100, record=other.get_record(second_key))
        boundary = capture(case)
        # This tests the lower L0 prerequisite and original CAS in one real
        # transaction, not a default consumer, L1 exception or funding gate.
        with db.db.transaction():
            case["api"].assert_native_order_boundary(db, boundary)
            assert db.acquire_open_intent(first_key, first_qty, "boundaryFirst", order_contract=first_contract,
                                          position_side=first_contract["execution"]["position_side"])
        original = other.get_record(second_key)
        with pytest.raises(CChanException):
            with other.db.transaction():
                case["api"].assert_native_order_boundary(other, boundary)
                other.acquire_open_intent(second_key, second_qty, "boundarySecond", order_contract=second_contract,
                                          position_side=second_contract["execution"]["position_side"])
        assert other.get_record(second_key) == original
        assert other.get_order_history(second_key)["attempts"] == []
        assert db.get_record(first_key)["open_attempt"] == 1
        assert len(case["trade"].exchange.created) == 3  # No transport/fill here.
        with pytest.raises(CChanException):
            capture(case)  # Old financial check cannot be recaptured as new L0.
    finally:
        other.close()


def test_nested_assertion_does_not_own_or_commit_the_callers_cas(boundary_case):
    case = boundary_case
    db = case["db"]
    key = db.add_signal(make_signal(code="TEST/USDT:USDT", is_buy=False))
    quantity, _, contract = case["trade"].prepare_order("TEST/USDT:USDT", 0.03, 100, record=db.get_record(key))
    boundary = capture(case)
    original = db.get_record(key)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with db.db.transaction():
            case["api"].assert_native_order_boundary(db, boundary)
            assert db.acquire_open_intent(key, quantity, "boundaryRollback", order_contract=contract,
                                          position_side=contract["execution"]["position_side"])
            assert db.db.conn.in_transaction
            raise RuntimeError("outer rollback")
    assert db.get_record(key) == original and db.get_order_history(key)["attempts"] == []
    with db.db.transaction():
        case["api"].assert_native_order_boundary(db, boundary)


def test_old_l0_cannot_erase_a_submitting_attempt_even_after_time_advances(boundary_case):
    case = boundary_case
    db = case["db"]
    key = db.add_signal(make_signal(code="TEST/USDT:USDT", is_buy=False))
    quantity, _, contract = case["trade"].prepare_order("TEST/USDT:USDT", 0.03, 100, record=db.get_record(key))
    boundary = capture(case)
    assert db.acquire_open_intent(key, quantity, "boundaryUnknown", order_contract=contract,
                                  position_side=contract["execution"]["position_side"])
    assert db.claim_order_submission(key, "open")
    original, history = db.get_record(key), db.get_order_history(key)
    case["clock"]["now"] += 10_000
    with db.db.transaction():
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(db, boundary)
    assert db.get_record(key) == original and db.get_order_history(key) == history
    assert original["open_order_status"] == "submitting" and original["open_order_id"] is None


def test_new_sticky_failure_invalidates_l0_and_never_releases_or_rewrites_it(boundary_case):
    case = boundary_case
    boundary = capture(case)
    other = CChanDB(db_conf=case["conf"])
    try:
        failed = other.reconcile_native_account(**{**case["request"], "wallet_ids": []})
        assert failed["payload"]["report"]["payload"]["status"] == "incomplete"
        with case["db"].db.transaction():
            with pytest.raises(CChanException):
                case["api"].assert_native_order_boundary(case["db"], boundary)
        assert case["db"].get_account_risk_state(case["arguments"]["account_context"])["frozen"]
    finally:
        other.close()


def test_fresh_unintegrated_native_balance_cannot_hide_behind_the_old_check(boundary_case, monkeypatch):
    case = boundary_case
    boundary = capture(case)
    from Trade.NativeBalanceReservations import collect_native_balance_reservations
    monkeypatch.setattr("Trade.NativeBalanceReservations.utc_now_ms", lambda: case["clock"]["now"])
    latest = collect_native_balance_reservations(case["client"], mode="testnet")
    assert latest["payload"]["finished_ms"] > case["params"]["balance_reservations"]["payload"]["finished_ms"]
    case["db"].store_native_account_observation(latest)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(case["db"], boundary)


def test_dangling_attempt_without_events_cannot_disappear_from_the_journal_prefix(boundary_case):
    case = boundary_case
    boundary = capture(case)
    db = case["db"].db
    row = db.query_one("SELECT * FROM chanpy_order_attempts ORDER BY record_id LIMIT 1")
    payload = json.loads(row["payload"])
    payload["identity"].update(record_id=999, attempt=1, client_order_id="danglingBoundary")
    row.update(record_id=999, attempt=1, client_order_id="danglingBoundary", payload=canonical_bytes(payload).decode())
    row["payload_sha256"] = hashlib.sha256(row["payload"].encode()).hexdigest()
    columns = list(row)
    db.execute(f"INSERT INTO chanpy_order_attempts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", tuple(row.values()))
    with db.transaction():
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(case["db"], boundary)


def test_explicit_windows_are_rechecked_inside_the_actual_transaction(boundary_case):
    case = boundary_case
    from .test_native_current_components import exact_policy
    case["arguments"]["policy"] = exact_policy(case)
    boundary = capture(case)
    with case["db"].db.transaction():
        case["api"].assert_native_order_boundary(case["db"], boundary)
    case["clock"]["now"] += 1
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            case["api"].assert_native_order_boundary(case["db"], boundary)


def test_capture_includes_owned_transaction_exit_latency(boundary_case, monkeypatch):
    case = boundary_case
    transaction = case["db"].db.transaction
    @contextmanager
    def delayed():
        with transaction():
            yield
        if not case["db"].db.conn.in_transaction:
            case["clock"]["now"] += 2001
    monkeypatch.setattr(case["db"].db, "transaction", delayed)
    with pytest.raises(CChanException):
        capture(case)


def test_core_only_restart_can_recheck_l0_without_sdk_or_config_file(boundary_case):
    case = boundary_case
    boundary = capture(case)
    script = """
import importlib.abc, json, sys
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','yaml','numpy','pandas','torch','sklearn','optuna','xgboost','lightgbm','PyQt6'}:
            raise ImportError('not installed')
sys.meta_path.insert(0, NoOptional())
from Trade.db_util import CChanDB
from Trade.SqliteDB import CSqliteDB
from Trade import NativeOrderBoundary as api
packet = json.load(sys.stdin)
api.utc_now_ms = lambda: packet['now']
chan = CChanDB.__new__(CChanDB)
chan.db_type, chan.table = 'sqlite', 'chan_trade'
chan.db = CSqliteDB(packet['database'], chan.table)
try:
    with chan.db.transaction():
        assert api.assert_native_order_boundary(chan, packet['boundary']) is None
finally:
    chan.close()
"""
    packet = {"database": case["conf"]["sqlite_path"], "boundary": boundary, "now": case["clock"]["now"]}
    result = subprocess.run([sys.executable, "-c", script], input=canonical_bytes(packet), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""


@pytest.mark.parametrize("operation", ["capture", "assert"])
def test_last_code_check_cannot_switch_to_an_unowned_database_connection(boundary_case, monkeypatch, operation):
    case = boundary_case
    boundary = capture(case)
    backend = case["db"].db
    original_connection, replacement = backend.conn, sqlite3.connect(":memory:")
    queries, reads = [], []
    replacement.set_trace_callback(queries.append)
    implementation = case["api"]._implementation
    def swapped():
        result = implementation()
        reads.append(1)
        if len(reads) == 2:
            backend.conn = replacement
        return result
    monkeypatch.setattr(case["api"], "_implementation", swapped)
    try:
        if operation == "capture":
            with pytest.raises(CChanException):
                capture(case)
        else:
            with backend.transaction():
                try:
                    with pytest.raises(CChanException):
                        case["api"].assert_native_order_boundary(case["db"], boundary)
                finally:
                    backend.conn = original_connection
        assert queries == [] and replacement.total_changes == 0
    finally:
        backend.conn = original_connection
        replacement.close()
