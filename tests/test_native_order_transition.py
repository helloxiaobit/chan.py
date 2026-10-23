"""Original CAS plus append-only exact deltas; no funding or transport permit."""
import importlib.util
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.db_util import CChanDB
from .test_native_order_boundary import boundary_case, capture
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_m6_trade import make_signal


def transition_api():
    assert importlib.util.find_spec("Trade.NativeOrderTransition") is not None, "original CAS native L1/L2 binding is missing"
    from Trade import NativeOrderTransition
    return NativeOrderTransition


def test_original_cas_transition_api_exists():
    api = transition_api()
    assert callable(api.read_native_order_transition)
    assert callable(api.assert_native_order_transition)


def new_order(case, code="TEST/USDT:USDT", client="nativeTransitionFirst", chan=None, *, native=True):
    chan = case["db"] if chan is None else chan
    key = chan.add_signal(make_signal(code=code, is_buy=False))
    quantity, _, contract = case["trade"].prepare_order(code, 0.03 if code.startswith("TEST") else 0.3, 100,
                                                      record=chan.get_record(key))
    if native:
        # A fresh synthetic request, never conversion of an existing intent.
        contract = {**contract, "schema": transition_api().CONTRACT_SCHEMA}
        contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    return key, dict(requested_qty=quantity, client_order_id=client, order_contract=contract,
                     position_side=contract["execution"]["position_side"])


@pytest.fixture()
def transition_case(boundary_case, monkeypatch):
    case = boundary_case
    api = transition_api()
    # The current-source fixture has advanced its fake clock past old fills.
    # New original CAS/journal timestamps must use that same synthetic clock.
    for module in (api.__name__, "Trade.OrderAudit", "Trade.db_util"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: case["clock"]["now"])
    return {**case, "transition": api}


def test_original_intent_restart_claim_persist_exact_l1_l2_without_http(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request = new_order(case)
    boundary = capture(case)
    original_contract = canonical_bytes(request["order_contract"])
    assert request["order_contract"]["schema"] == "chan-native-cas-order-v1"
    assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
    l1 = api.read_native_order_transition(chan, key)
    assert l1["schema"] == "chan-native-order-transition-v1"
    assert l1["payload"]["stage"] == "intent"
    assert l1["payload"]["boundary"] == boundary
    assert l1["payload"]["previous_sha256"] is None
    assert l1["payload"]["economics_complete"] is l1["payload"]["native_admission_verified"] is False
    history = chan.get_order_history(key)
    assert [event["kind"] for event in history["attempts"][0]["events"]] == ["intent"]
    assert history["attempts"][0]["events"][0]["native_boundary_sha256"] == l1["payload"]["binding_sha256"]
    assert chan.get_record(key)["open_order_contract"].encode() == original_contract
    restarted = CChanDB(db_conf=case["conf"])
    try:
        # No caller L1/expected ledger: the original claim loads its own binding.
        assert restarted.claim_order_submission(key, "open")
        l2 = api.read_native_order_transition(restarted, key)
        assert l2["payload"]["stage"] == "claim"
        assert l2["payload"]["previous_sha256"] == l1["payload_sha256"]
        with restarted.db.transaction():
            assert api.assert_native_order_transition(restarted, key) is None
        assert not restarted.claim_order_submission(key, "open")
        assert api.read_native_order_transition(restarted, key) == l2
        assert [event["kind"] for event in restarted.get_order_history(key)["attempts"][0]["events"]] == ["intent", "claim"]
        assert restarted.get_record(key)["open_order_status"] == "submitting"
        assert restarted.get_record(key)["open_order_id"] is None
        assert len(case["trade"].exchange.created) == 3
    finally:
        restarted.close()


def test_resealed_projection_summary_cannot_replace_original_event_binding(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request = new_order(case)
    assert chan.acquire_open_intent(key, **request, native_boundary=capture(case))
    document = copy.deepcopy(api.read_native_order_transition(chan, key))
    # Emulate corruption with a fresh checksum. The original append-only
    # journal remains byte-identical and must disprove this replacement.
    with chan.db.transaction():
        chan.db.execute(f"UPDATE {chan.table} SET unwatch_reason='not the original CAS' WHERE id=?", (key,))
        document["payload"]["after_record_sha256"] = hashlib.sha256(canonical_bytes(chan.get_record(key))).hexdigest()
        document["payload"]["records_sha256"] = hashlib.sha256(canonical_bytes(api._records(chan))).hexdigest()
        document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
        trigger = api.TABLE+"_no_update"
        chan.db.execute(f"DROP TRIGGER {trigger}")
        chan.db.execute(f"UPDATE {api.TABLE} SET payload=?,payload_sha256=? WHERE record_id=?",
                        (canonical_bytes(document).decode(), hashlib.sha256(canonical_bytes(document)).hexdigest(), key))
        chan.db.execute(api.SCHEMA[trigger])
    with pytest.raises(CChanException):
        chan.claim_order_submission(key, "open")
    assert chan.get_record(key)["open_order_status"] == "created"
    assert len(chan.get_order_history(key)["attempts"][0]["events"]) == 1


def test_l2_does_not_hide_a_dangling_unjournaled_attempt(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request = new_order(case)
    assert chan.acquire_open_intent(key, **request, native_boundary=capture(case))
    assert chan.claim_order_submission(key, "open")
    row = chan.db.query_one("SELECT * FROM chanpy_order_attempts ORDER BY record_id LIMIT 1")
    payload = json.loads(row["payload"])
    payload["identity"].update(record_id=999, attempt=1, client_order_id="transitionDangling")
    row.update(record_id=999, attempt=1, client_order_id="transitionDangling", payload=canonical_bytes(payload).decode())
    row["payload_sha256"] = hashlib.sha256(row["payload"].encode()).hexdigest()
    columns = list(row)
    chan.db.execute(f"INSERT INTO chanpy_order_attempts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", tuple(row.values()))
    with chan.db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_order_transition(chan, key)


def native_intent(case, *, claim=False):
    key, request = new_order(case)
    boundary = capture(case)
    assert case["db"].acquire_open_intent(key, **request, native_boundary=boundary)
    if claim:
        assert case["db"].claim_order_submission(key, "open")
    return key, request, boundary


@pytest.mark.parametrize("other_table", [False, True])
def test_bound_cas_competition_uses_one_l0_across_markets_tables_and_connections(transition_case, other_table):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    other = CChanDB(db_conf=case["conf"], table_name="transition_signals" if other_table else chan.table)
    try:
        first, request = new_order(case)
        second, competing = new_order(case, "ALT/USDT:USDT", "nativeCompeting", other)
        boundary = capture(case)
        second_before = other.get_record(second)
        assert chan.acquire_open_intent(first, **request, native_boundary=boundary)
        with pytest.raises(CChanException):
            other.acquire_open_intent(second, **competing, native_boundary=boundary)
        assert other.get_record(second) == second_before
        assert other.get_order_history(second)["attempts"] == []
        assert chan.db.query_one(f"SELECT count(*) AS n FROM {api.TABLE}")["n"] == 1
        assert len(case["trade"].exchange.created) == 3
    finally:
        other.close()


@pytest.mark.parametrize("stage", ["intent", "claim"])
@pytest.mark.parametrize("damage", ["own_field", "other_field", "new_signal", "foreign_intent"])
def test_any_unapproved_whole_record_or_journal_change_stops_next_boundary(transition_case, stage, damage):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    # This signal is also frozen into L1's full records, not silently excluded.
    spare, request = new_order(case, "ALT/USDT:USDT", "nativeForeign", native=False)
    key, _, _ = native_intent(case, claim=stage == "claim")
    before_events = len(chan.get_order_history(key)["attempts"][0]["events"])
    other = CChanDB(db_conf=case["conf"])
    try:
        if damage in {"own_field", "other_field"}:
            changed = key if damage == "own_field" else case["key"]
            other.db.execute(f"UPDATE {chan.table} SET unwatch_reason='external change' WHERE id=?", (changed,))
        elif damage == "new_signal":
            other.add_signal(make_signal(code="THIRD/USDT:USDT", is_buy=False))
        else:
            # Even a pre-existing legacy direct CAS is not an allowed delta
            # of our bound native intent. Its own original behavior is intact.
            assert other.acquire_open_intent(spare, **request)
        with pytest.raises(CChanException):
            if stage == "intent":
                chan.claim_order_submission(key, "open")
            else:
                with chan.db.transaction():
                    api.assert_native_order_transition(chan, key)
        assert len(chan.get_order_history(key)["attempts"][0]["events"]) == before_events
        assert len(case["trade"].exchange.created) == 3
    finally:
        other.close()


@pytest.mark.parametrize("stage", ["intent", "claim"])
@pytest.mark.parametrize("damage", ["expired", "freeze", "balance"])
def test_every_bound_use_rechecks_original_sources_freeze_and_explicit_time(transition_case, monkeypatch, stage, damage):
    case, api = transition_case, transition_case["transition"]
    from .test_native_current_components import exact_policy, collect_later
    if damage == "expired":
        case["arguments"]["policy"] = exact_policy(case)
    key, _, _ = native_intent(case, claim=stage == "claim")
    before = case["db"].get_record(key)
    if damage == "expired":
        case["clock"]["now"] += 1
    elif damage == "freeze":
        failed = case["db"].reconcile_native_account(**{**case["request"], "wallet_ids": []})
        assert failed["payload"]["report"]["payload"]["status"] == "incomplete"
    else:
        collect_later(case, monkeypatch, case["arguments"]["account_context"]["venue"], "balance")
    with pytest.raises(CChanException):
        if stage == "intent":
            case["db"].claim_order_submission(key, "open")
        else:
            with case["db"].db.transaction():
                api.assert_native_order_transition(case["db"], key)
    assert case["db"].get_record(key) == before
    assert len(case["trade"].exchange.created) == 3


@pytest.mark.parametrize("stage", ["intent", "claim"])
def test_boundary_publication_failure_rolls_back_original_cas_and_journal(transition_case, monkeypatch, stage):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request = new_order(case)
    boundary = capture(case)
    if stage == "claim":
        assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
    record, history = chan.get_record(key), chan.get_order_history(key)
    execute = chan.db.execute
    def fail_reference(sql, args=()):
        if sql.startswith("INSERT INTO "+api.TABLE):
            raise sqlite3.OperationalError("synthetic publication failure")
        return execute(sql, args)
    monkeypatch.setattr(chan.db, "execute", fail_reference)
    with pytest.raises(CChanException):
        if stage == "intent":
            chan.acquire_open_intent(key, **request, native_boundary=boundary)
        else:
            chan.claim_order_submission(key, "open")
    assert chan.get_record(key) == record and chan.get_order_history(key) == history
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {api.TABLE}")["n"] == (stage == "claim")


@pytest.mark.parametrize("stage", ["intent", "claim"])
def test_outer_owner_can_rollback_exactly_its_cas_and_reference(transition_case, stage):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request = new_order(case)
    boundary = capture(case)
    if stage == "claim":
        assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
    record, history = chan.get_record(key), chan.get_order_history(key)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with chan.db.transaction():
            if stage == "intent":
                assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
            else:
                assert chan.claim_order_submission(key, "open")
            assert chan.db.conn.in_transaction
            raise RuntimeError("outer rollback")
    assert chan.get_record(key) == record and chan.get_order_history(key) == history
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {api.TABLE}")["n"] == (stage == "claim")


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
def test_original_transition_references_are_append_only(transition_case, operation):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, _, _ = native_intent(case)
    original = api.read_native_order_transition(chan, key)
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "UPDATE":
            chan.db.execute(f"UPDATE {api.TABLE} SET binding_sha256='changed'")
        elif operation == "DELETE":
            chan.db.execute(f"DELETE FROM {api.TABLE}")
        else:
            chan.db.execute(f"INSERT OR REPLACE INTO {api.TABLE} SELECT * FROM {api.TABLE}")
    assert api.read_native_order_transition(chan, key) == original


def test_reset_reference_table_cannot_downgrade_original_bound_claim(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, _, _ = native_intent(case)
    original = chan.get_order_history(key)
    with chan.db.transaction():
        chan.db.execute(f"DROP TABLE {api.TABLE}")
        api.initialize_schema(chan.db.conn)
    with pytest.raises(CChanException):
        chan.claim_order_submission(key, "open")
    assert chan.get_order_history(key) == original
    assert chan.get_record(key)["open_order_status"] == "created"


def test_claim_unknown_never_releases_or_recreates_old_native_intent(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request, boundary = native_intent(case, claim=True)
    original = chan.get_order_history(key)
    case["clock"]["now"] += 10_000
    assert not chan.claim_order_submission(key, "open")
    with pytest.raises(CChanException):
        chan.acquire_open_intent(key, **request)
    with pytest.raises(CChanException):
        chan.acquire_open_intent(key, **request, native_boundary=boundary)
    assert chan.get_order_history(key) == original
    assert chan.get_record(key)["open_order_id"] is None
    assert chan.get_record(key)["open_order_status"] == "submitting"
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {api.TABLE}")["n"] == 2


def test_bound_history_survives_original_ack_reports_without_fresh_recovery_gates(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, request, _ = native_intent(case, claim=True)
    reference = api.read_native_order_transition(chan, key)
    case["clock"]["now"] += 10_000  # Historical reads/reports are not new sends.
    chan.record_order_ack(key, "open", "nativeServer", client_order_id=request["client_order_id"], expected_attempt=1)
    chan.apply_open_fill(key, request["requested_qty"], 100, "closed", client_order_id=request["client_order_id"],
                         order_id="nativeServer", expected_attempt=1)
    assert api.read_native_order_transition(chan, key) == reference
    assert [e["kind"] for e in chan.get_order_history(key)["attempts"][0]["events"]] == ["intent", "claim", "ack", "report"]
    with chan.db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_order_transition(chan, key)


def test_native_transition_current_assertion_requires_original_owned_transaction(transition_case):
    case, api = transition_case, transition_case["transition"]
    key, _, _ = native_intent(case, claim=True)
    with pytest.raises(CChanException):
        api.assert_native_order_transition(case["db"], key)


def test_reference_reopens_without_optional_sdk_yaml_or_actual_configuration(transition_case):
    case = transition_case
    key, _, _ = native_intent(case, claim=True)
    script = """
import importlib.abc, json, sys
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','yaml','numpy','pandas','torch','sklearn','optuna','xgboost','lightgbm','PyQt6'}:
            raise ImportError('not installed')
sys.meta_path.insert(0, NoOptional())
from Trade.db_util import CChanDB
from Trade.SqliteDB import CSqliteDB
from Trade import NativeOrderTransition as api
packet = json.load(sys.stdin)
for name in ('Trade.NativeOrderTransition','Trade.NativeOrderBoundary','Trade.NativeAdmission','Trade.NativeCurrentComponents','Trade.NativeAccountCheck','Trade.AccountRiskStore'):
    sys.modules[name].utc_now_ms = lambda: packet['now']
chan = CChanDB.__new__(CChanDB)
chan.db_type, chan.table = 'sqlite', 'chan_trade'
chan.db = CSqliteDB(packet['database'], chan.table)
try:
    assert api.read_native_order_transition(chan, packet['key'])['payload']['stage'] == 'claim'
    with chan.db.transaction():
        assert api.assert_native_order_transition(chan, packet['key']) is None
finally:
    chan.close()
"""
    packet = {"database": case["conf"]["sqlite_path"], "key": key, "now": case["clock"]["now"]}
    result = subprocess.run([sys.executable, "-c", script], input=canonical_bytes(packet), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""


def test_direct_engine_cannot_spend_a_consistency_only_native_binding(transition_case, monkeypatch):
    case = transition_case
    key, request, _ = native_intent(case)
    def forbidden_get():
        pytest.fail("consistency-only bound intent reached exchange lookup before its missing-funding gate")
    monkeypatch.setattr(case["trade"], "get_exchange", forbidden_get)
    with pytest.raises(CChanException, match="一致性.*资金"):
        case["trade"].place_order("TEST/USDT:USDT", False, request["requested_qty"], 100,
                                   client_order_id=request["client_order_id"], position_side=request["position_side"])
    assert case["db"].get_record(key)["open_order_status"] == "created"
    assert len(case["db"].get_order_history(key)["attempts"][0]["events"]) == 1
    assert len(case["trade"].exchange.created) == 3


@pytest.mark.parametrize("at", [1, 2])
def test_native_l2_code_check_cannot_query_a_replacement_connection(transition_case, monkeypatch, at):
    case, api = transition_case, transition_case["transition"]
    key, _, _ = native_intent(case, claim=True)
    backend = case["db"].db
    original, replacement = backend.conn, sqlite3.connect(":memory:")
    queries, reads = [], []
    replacement.set_trace_callback(queries.append)
    implementation = api._implementation
    def swapped():
        result = implementation()
        reads.append(1)
        if len(reads) == at:
            backend.conn = replacement
        return result
    monkeypatch.setattr(api, "_implementation", swapped)
    try:
        with backend.transaction():
            try:
                with pytest.raises(CChanException):
                    api.assert_native_order_transition(case["db"], key)
            finally:
                backend.conn = original
        assert queries == [] and replacement.total_changes == 0
    finally:
        backend.conn = original
        replacement.close()


def test_unaware_strict_execution_reader_also_rejects_new_diagnostic_contract(transition_case):
    case = transition_case
    key, _, _ = native_intent(case)
    # This is the original strict contract reader, not the new marker gate.
    with pytest.raises(CChanException):
        case["trade"]._read_order_contract("TEST/USDT:USDT", {"phase": "open", "record": case["db"].get_record(key)})


def test_native_binding_cannot_silently_reuse_a_regular_v3_execution_contract(transition_case):
    case = transition_case
    key, request = new_order(case)
    request["order_contract"]["schema"] = "chan-ccxt-order-v3"
    contract = request["order_contract"]
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    before = case["db"].get_record(key)
    with pytest.raises(CChanException):
        case["db"].acquire_open_intent(key, **request, native_boundary=capture(case))
    assert case["db"].get_record(key) == before


def test_new_diagnostic_schema_requires_its_explicit_original_l0(transition_case):
    case = transition_case
    key, request = new_order(case)
    contract = request["order_contract"]
    contract["schema"] = "chan-native-cas-order-v1"
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    before = case["db"].get_record(key)
    with pytest.raises(CChanException):
        case["db"].acquire_open_intent(key, **request)
    assert case["db"].get_record(key) == before


def test_resealed_duplicate_boundary_must_match_original_root_bytes_not_bool_aliases(transition_case):
    case, api = transition_case, transition_case["transition"]
    chan = case["db"]
    key, _, _ = native_intent(case)
    document = copy.deepcopy(api.read_native_order_transition(chan, key))
    document["payload"]["boundary"]["payload"]["native_admission_verified"] = 0
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    with chan.db.transaction():
        trigger = api.TABLE+"_no_update"
        chan.db.execute(f"DROP TRIGGER {trigger}")
        chan.db.execute(f"UPDATE {api.TABLE} SET payload=?,payload_sha256=? WHERE record_id=?",
                        (canonical_bytes(document).decode(), hashlib.sha256(canonical_bytes(document)).hexdigest(), key))
        chan.db.execute(api.SCHEMA[trigger])
    with pytest.raises(CChanException):
        api.read_native_order_transition(chan, key)


def test_normal_sqlite_integer_score_is_not_mistaken_for_an_unapproved_cas_delta(transition_case):
    case = transition_case
    key, request = new_order(case)
    assert case["db"].acquire_open_intent(key, **request, score_before=1, native_boundary=capture(case))
    assert case["db"].get_record(key)["model_score_before"] == 1.0
    assert case["db"].claim_order_submission(key, "open")


@pytest.mark.parametrize("stage", ["intent", "claim"])
def test_original_writer_cannot_expand_the_allowed_delta_by_adding_update_fields(transition_case, monkeypatch, stage):
    case = transition_case
    chan = case["db"]
    key, request = new_order(case)
    boundary = capture(case)
    if stage == "claim":
        assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
    record, history = chan.get_record(key), chan.get_order_history(key)
    write = chan._order_write
    def extra_update(record_id, prefix, kind, sql, args, **options):
        if kind == stage:
            options["native_updates"] = {**options["native_updates"], "unwatch_reason": "not an original allowed field"}
            sql = sql.replace(" SET ", " SET unwatch_reason='not an original allowed field', ", 1)
        return write(record_id, prefix, kind, sql, args, **options)
    monkeypatch.setattr(chan, "_order_write", extra_update)
    with pytest.raises(CChanException):
        if stage == "intent":
            chan.acquire_open_intent(key, **request, native_boundary=boundary)
        else:
            chan.claim_order_submission(key, "open")
    assert chan.get_record(key) == record and chan.get_order_history(key) == history


@pytest.mark.parametrize("damage", ["market_precision", "execution_mode"])
def test_native_terms_must_match_declared_l0_market_and_original_leg_rules(transition_case, damage):
    case = transition_case
    key, request = new_order(case)
    contract = request["order_contract"]
    if damage == "market_precision":
        contract["market"]["precision"]["amount"] *= 10
    else:
        contract["execution"]["position_mode"] = "hedged" if contract["execution"]["position_mode"] == "one_way" else "one_way"
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    before = case["db"].get_record(key)
    with pytest.raises(CChanException):
        case["db"].acquire_open_intent(key, **request, native_boundary=capture(case))
    assert case["db"].get_record(key) == before


def test_foreign_transition_table_is_not_adopted_and_initialization_is_atomic(tmp_path):
    api = transition_api()
    path = tmp_path/"foreign-transition.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE {api.TABLE}(original TEXT)")
        conn.execute(f"INSERT INTO {api.TABLE} VALUES('retain')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(path)})
    with sqlite3.connect(path) as conn:
        assert conn.execute(f"SELECT * FROM {api.TABLE}").fetchall() == [("retain",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chan_trade'").fetchall() == []


@pytest.mark.parametrize("suffix", ["", "_no_update"])
def test_transition_table_and_guard_names_are_reserved_for_original_schema(tmp_path, suffix):
    api = transition_api()
    path = tmp_path/"reserved-transition.db"
    with pytest.raises(ValueError, match="Reserved"):
        CChanDB(table_name=api.TABLE+suffix, db_conf={"type": "sqlite", "sqlite_path": str(path)})
    assert not path.exists()


@pytest.mark.parametrize("stage", ["intent", "claim"])
@pytest.mark.parametrize("latency", ["publication", "readback"])
def test_original_cas_budget_includes_reference_publication_and_final_readback(transition_case, monkeypatch, stage, latency):
    case, api = transition_case, transition_case["transition"]
    from .test_native_current_components import exact_policy
    chan = case["db"]
    key, request = new_order(case)
    case["arguments"]["policy"] = exact_policy(case)
    boundary = capture(case)
    if stage == "claim":
        assert chan.acquire_open_intent(key, **request, native_boundary=boundary)
    record, history = chan.get_record(key), chan.get_order_history(key)
    delayed = []
    if latency == "publication":
        execute = chan.db.execute
        def publication(sql, args=()):
            result = execute(sql, args)
            if sql.startswith("INSERT INTO "+api.TABLE):
                delayed.append(1)
                case["clock"]["now"] += 1
            return result
        monkeypatch.setattr(chan.db, "execute", publication)
    else:
        read = api._read
        def readback(*args):
            result = read(*args)
            if result["payload"]["stage"] == stage and not delayed:
                delayed.append(1)
                case["clock"]["now"] += 1
            return result
        monkeypatch.setattr(api, "_read", readback)
    with pytest.raises(CChanException):
        if stage == "intent":
            chan.acquire_open_intent(key, **request, native_boundary=boundary)
        else:
            chan.claim_order_submission(key, "open")
    assert delayed == [1]
    assert chan.get_record(key) == record and chan.get_order_history(key) == history
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {api.TABLE}")["n"] == (stage == "claim")
    assert len(case["trade"].exchange.created) == 3


def test_legacy_unbound_cas_is_not_subject_to_native_only_exact_owner_restrictions(tmp_path):
    class LegacyChanDB(CChanDB):
        pass
    chan = LegacyChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"legacy-subclass.db")})
    try:
        key = chan.add_signal(make_signal())
        assert chan.acquire_open_intent(key, 10, "legacySubclass")
        assert chan.claim_order_submission(key, "open")
        history = chan.get_order_history(key)
        assert [e["kind"] for e in history["attempts"][0]["events"]] == ["intent", "claim"]
        assert all("native_boundary_sha256" not in e for e in history["attempts"][0]["events"])
    finally:
        chan.close()
