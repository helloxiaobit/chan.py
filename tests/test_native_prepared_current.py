"""Persisted intent currentness uses original local facts, never new admission."""
import copy
import gc
import json
from contextlib import closing
from pathlib import Path

import pytest

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from OfflineData.offline_data_util import CKLineDB
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.db_util import CChanDB
from Trade.Script.OpeningInputs import COpeningInputs
from .native_order_preparation_case import native_order_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_prepared_intent import acquire, make_case


def current_api():
    from Trade import NativePreparedIntent
    method = getattr(NativePreparedIntent, "assert_native_prepared_intent_current", None)
    assert callable(method), "persisted prepared intent has no original local reconstitution"
    return method


def test_persisted_prepared_current_api_exists():
    current_api()


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(m, s) for m in ("one_way", "hedged") for s in (True, False)])
def test_persisted_original_intent_has_a_read_only_current_view_without_its_live_handle(store, tmp_path, monkeypatch, venue, mode, side):
    from Trade import NativePreparedIntent, NativePreparation
    case = native_order_case(*store, tmp_path, monkeypatch, venue, mode=mode, side=side)
    monkeypatch.setattr(NativePreparedIntent, "utc_now_ms", lambda: case["clock"]["now"])
    assert acquire(case)
    gc.collect()
    assert not NativePreparation._PREPARED
    before, changes, trace = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes, list(case["trace"])
    with case["db"].db.transaction():
        assert current_api()(case["trade"], case["key"]) is None
    assert case["db"].get_record(case["key"]) == before
    assert case["db"].db.conn.total_changes == changes and case["trace"] == trace
    with pytest.raises(CChanException):
        case["db"].claim_order_submission(case["key"], "open")


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_new_engine_guard_and_connection_reconstruct_local_state_without_reprepare(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    with closing(CChanDB(db_conf=store[1])) as reopened:
        engine = copy.copy(case["trade"])
        engine.chan_db = reopened
        engine.opening_inputs = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"])
        trace, changes = list(case["trace"]), reopened.db.conn.total_changes
        with reopened.db.transaction():
            assert current_api()(engine, case["key"]) is None
        assert reopened.db.conn.total_changes == changes and case["trace"] == trace
        with pytest.raises(CChanException):
            reopened.claim_order_submission(case["key"], "open")


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("field", ["options", "apiKey", "secret", "password"])
def test_current_sdk_state_cannot_replace_the_original_invocation_baseline(store, tmp_path, monkeypatch, venue, field):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    if field == "options":
        case["client"].options["unobserved-option-change"] = True
    else:
        setattr(case["client"], field, "unobserved-client-change")
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            current_api()(case["trade"], case["key"])


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_diagnostic_current_view_cannot_become_engine_monetary_permission(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    db, engine = case["db"], case["trade"]
    after = db.get_record(case["key"])
    transition = read_native_order_transition(db, case["key"])
    payload = transition["payload"]
    assert transition["schema"] == "chan-native-order-transition-v2"
    assert payload["stage"] == "intent"
    assert payload["root"]["preparation"]["schema"] == "chan-native-prepared-intent-binding-v2"
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    original = canonical_bytes([db.query_all(), db.get_order_history(case["key"]), transition])
    trace, changes = copy.deepcopy(case["trace"]), db.db.conn.total_changes
    # A real read-only current view does not turn this old diagnostic into v4.
    with db.db.transaction():
        assert current_api()(engine, case["key"]) is None
    with pytest.raises(CChanException, match="仅证明一致性") as denied:
        case["trade"]._validated_persisted_intent(after["stock_code"], bool(after["is_buy"]), after["open_requested_qty"],
            after["open_client_order_id"], False, after["position_side"])
    assert denied.value.errcode == ErrCode.TRADE_UNLOCK_FAIL
    with pytest.raises(CChanException, match="仅证明一致性") as denied:
        engine.place_order(after["stock_code"], bool(after["is_buy"]), after["open_requested_qty"], 100,
            client_order_id=after["open_client_order_id"], position_side=after["position_side"])
    assert denied.value.errcode == ErrCode.TRADE_UNLOCK_FAIL
    with pytest.raises(CChanException):
        db.claim_order_submission(case["key"], "open")
    assert db.get_record(case["key"]) == after and case["trace"] == trace
    assert canonical_bytes([db.query_all(), db.get_order_history(case["key"]),
                            read_native_order_transition(db, case["key"])]) == original
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["record", "other_row", "config", "candidate", "kill", "bars", "scope",
                                  "engine_config", "metadata", "public_route", "private_route", "loader", "freeze", "age", "reverse_clock"])
def test_current_local_and_original_ledger_changes_refuse_without_refresh_or_writes(store, tmp_path, monkeypatch, venue, damage):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    db, engine, client = case["db"], case["trade"], case["client"]
    if damage in {"record", "other_row"}:
        key = case["key"] if damage == "record" else case["history_keys"][0]
        db.db.execute(f"UPDATE {db.table} SET unwatch_reason='local-current-drift' WHERE id=?", (key,))
    elif damage == "config":
        case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
    elif damage == "candidate":
        path = Path(engine.safety_policy.strategy_receipt["path"])
        document = json.loads(path.read_bytes())
        document["unobserved_field"] = "changed"
        path.write_bytes(canonical_bytes(document))
    elif damage == "kill":
        engine.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    elif damage == "bars":
        with CKLineDB(str(case["market_path"])) as market:
            market.conn.execute("UPDATE kline SET v=7 WHERE symbol='ALT/USDT:USDT'")
            market.conn.commit()
    elif damage == "scope":
        engine.opening_inputs._scope["code_list"] = ["TEST/USDT:USDT"]
    elif damage == "engine_config":
        engine.ccxt_conf["leverage"] = 4
    elif damage == "metadata":
        client.markets["TEST/USDT:USDT"]["precision"]["price"] = .2
    elif damage in {"public_route", "private_route"}:
        key = ("fapiPublic" if damage == "public_route" else "fapiPrivate") if venue == "binance" else "rest"
        client.urls["api"][key] = "https://not-the-original.invalid"
    elif damage == "loader":
        monkeypatch.setattr(client, "load_markets", lambda *a, **k: pytest.fail("current view tried a replaced loader"))
    elif damage == "freeze":
        db.reconcile_account(account_context=case["before"]["payload"]["account_context"], before_id="0"*64, after_id="1"*64,
                             wallet_ids=[], execution_scan_ids=[])
    elif damage == "age":
        case["clock"]["now"] += 2001
    else:
        case["clock"]["now"] -= 1
    after, trace, changes = db.get_record(case["key"]), list(case["trace"]), db.db.conn.total_changes
    with db.db.transaction():
        with pytest.raises(CChanException):
            current_api()(engine, case["key"])
    assert db.get_record(case["key"]) == after and case["trace"] == trace and db.db.conn.total_changes == changes


@pytest.mark.parametrize("raw", [False, True])
def test_only_original_owned_transaction_can_reconstitute_local_state(store, tmp_path, monkeypatch, raw):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    assert acquire(case)
    if raw:
        case["db"].db.conn.execute("BEGIN")
    try:
        with pytest.raises(CChanException):
            current_api()(case["trade"], case["key"])
    finally:
        if raw:
            case["db"].db.conn.rollback()


@pytest.mark.parametrize("field", ["document", "expected_record", "persisted_record_sha256", "policy", "passed"])
def test_public_current_entry_accepts_no_caller_proof_or_state_exemption(store, tmp_path, monkeypatch, field):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    assert acquire(case)
    with case["db"].db.transaction():
        with pytest.raises(TypeError):
            current_api()(case["trade"], case["key"], **{field: True})


@pytest.mark.parametrize("bad", [None, True, "0"*63, "A"*64])
def test_binding_v2_client_digest_is_strictly_typed_while_v1_historical_shape_is_retained(store, tmp_path, monkeypatch, bad):
    from Trade import NativePreparedIntent
    case = make_case(store, tmp_path, monkeypatch, "binance")
    assert acquire(case)
    root = read_native_order_transition(case["db"], case["key"])["payload"]["root"]
    attempt = case["db"].get_order_history(case["key"])["attempts"][0]
    legacy = copy.deepcopy(root)
    legacy["preparation"]["schema"] = "chan-native-prepared-intent-binding-v1"
    del legacy["preparation"]["client_binding_sha256"]
    with case["db"].db.transaction():
        assert NativePreparedIntent.validate_stored_preparation(case["db"], legacy, attempt) is None
        root["preparation"]["client_binding_sha256"] = bad
        with pytest.raises(CChanException):
            NativePreparedIntent.validate_stored_preparation(case["db"], root, attempt)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["candidate", "client", "other_row"])
def test_local_risk_callback_cannot_leave_a_late_mutation_outside_reconstitution(store, tmp_path, monkeypatch, venue, damage):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    original = case["db"].assert_account_new_risk_allowed
    def late(account):
        original(account)
        if damage == "client":
            case["client"].secret = "late-sdk-credential-change"
        elif damage == "candidate":
            path = Path(case["trade"].safety_policy.strategy_receipt["path"])
            path.write_bytes(path.read_bytes()+b"\n ")
        else:
            case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='late-current-row' WHERE id=?",
                                  (case["history_keys"][0],))
    monkeypatch.setattr(case["db"], "assert_account_new_risk_allowed", late)
    trace = list(case["trace"])
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            current_api()(case["trade"], case["key"])
    assert case["trace"] == trace and case["db"].get_record(case["key"])["open_order_status"] == "created"


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_persisted_client_baseline_contains_only_a_digest_not_sdk_credentials(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    private = "fake-only-private-sdk-value-not-for-publication"
    case["client"].apiKey = private
    case["client"].secret = private
    case["client"].password = private
    assert acquire(case)
    document = read_native_order_transition(case["db"], case["key"])
    assert private.encode() not in canonical_bytes(document)
    with case["db"].db.transaction():
        assert current_api()(case["trade"], case["key"]) is None
