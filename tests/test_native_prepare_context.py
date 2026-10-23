"""Live local prepare contexts for an owned SQLite view, never admission."""
import copy
import gc
import json
import weakref
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from .test_native_preparation import NOW, prepare_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment


def context_api():
    from Trade import NativePreparation
    assert callable(getattr(NativePreparation, "_capture_native_prepare_context", None)), "owned prepare context is missing"
    assert callable(getattr(NativePreparation, "assert_native_prepare_context_current", None)), "no-GET owned assertion is missing"
    return NativePreparation


def test_owned_prepare_context_api_exists():
    context_api()


def prepared(case):
    return context_api()._capture_native_prepare_context(case["trade"], case["key"], .037, 100)


def no_native_io(case, monkeypatch):
    client = case["trade"].exchange
    for name in ("request", "fetch_position_mode", "fetch_leverage", "create_order", "load_markets"):
        monkeypatch.setattr(client, name, lambda *args, **kwargs: pytest.fail("no SDK I/O or prepare is allowed in the owned assertion"))


def test_owned_assertion_reuses_actual_context_without_prepare_or_sdk_calls(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    context = prepared(case)
    before, changes = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        assert api.assert_native_prepare_context_current(case["trade"], context) is None
        assert case["db"].db.conn.in_transaction
    assert case["db"].get_record(case["key"]) == before
    assert case["db"].db.conn.total_changes == changes


@pytest.mark.parametrize("kind", ["document", "copied", "constructed", "passed"])
def test_external_or_copied_proof_is_not_the_actual_prepare_invocation(prepare_case, monkeypatch, kind):
    case, api = prepare_case, context_api()
    context = prepared(case)
    supplied = ({"schema": "chan-native-prepare-identity-v1", "passed": True} if kind == "document" else
                copy.copy(context) if kind == "copied" else type(context)() if kind == "constructed" else True)
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], supplied)


def test_context_is_pre_intent_and_requires_the_original_owned_transaction(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    context = prepared(case)
    no_native_io(case, monkeypatch)
    with pytest.raises(CChanException):
        api.assert_native_prepare_context_current(case["trade"], context)
    assert not case["db"].db.conn.in_transaction


def test_context_use_clock_cannot_move_back_before_the_actual_prepare(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    case["clock"]["now"] = NOW+100
    context = prepared(case)
    case["clock"]["now"] -= 1
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)


@pytest.mark.parametrize("bad", [None, True, -1, NOW+.5, 2**63])
def test_context_use_clock_is_exact_and_finite_without_coercion(prepare_case, monkeypatch, bad):
    case, api = prepare_case, context_api()
    context = prepared(case)
    monkeypatch.setattr(api, "utc_now_ms", lambda: bad)
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)


@pytest.mark.parametrize("damage", ["record", "configuration", "candidate"])
def test_end_clock_does_not_leave_a_late_mutation_outside_the_local_check(prepare_case, monkeypatch, damage):
    case, api = prepare_case, context_api()
    context = prepared(case)
    ticks = []
    def clock():
        ticks.append(1)
        if len(ticks) == 2:
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='late context change' WHERE id=?", (case["key"],))
            elif damage == "configuration":
                case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
            else:
                path = Path(case["trade"].safety_policy.strategy_receipt["path"])
                value = json.loads(path.read_bytes())
                value["new_observation"] = "late"
                path.write_text(json.dumps(value), encoding="utf-8")
        return case["clock"]["now"]
    monkeypatch.setattr(api, "utc_now_ms", clock)
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)
    assert ticks == [1, 1]


@pytest.mark.parametrize("damage", ["record", "config", "candidate", "kill", "unlock", "cache", "options", "route",
                                   "engine_config", "scope", "client_owner", "database_owner"])
def test_original_local_inputs_owners_and_observed_client_data_cannot_drift(prepare_case, monkeypatch, damage):
    case, api = prepare_case, context_api()
    context = prepared(case)
    no_native_io(case, monkeypatch)
    if damage == "record":
        case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='changed after prepare' WHERE id=?", (case["key"],))
    elif damage == "config":
        case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
    elif damage == "candidate":
        path = Path(case["trade"].safety_policy.strategy_receipt["path"])
        value = json.loads(path.read_bytes())
        value["new_observation"] = "changed"
        path.write_text(json.dumps(value), encoding="utf-8")
    elif damage == "kill":
        case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    elif damage == "unlock":
        case["trade"].safety_policy.environ.pop("CHANPY_ENABLE_TESTNET")
    elif damage == "cache":
        case["trade"].exchange.markets["TEST/USDT:USDT"]["contractSize"] = 2
    elif damage == "options":
        case["trade"].exchange.options["new_context_option"] = True
    elif damage == "route":
        case["trade"].exchange.urls["api"]["rest"] = "https://wrong.example/"
    elif damage == "engine_config":
        case["trade"].ccxt_conf["leverage"] = 4
    elif damage == "scope":
        case["guard"]._scope["code_list"] = ["TEST/USDT:USDT"]
    elif damage == "client_owner":
        case["trade"].exchange = object()
    else:
        case["trade"].chan_db = object()
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)


def test_a_matching_engine_copy_is_not_the_original_invocation_owner(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    context = prepared(case)
    borrower = copy.copy(case["trade"])
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(borrower, context)


def test_a_raw_begin_is_not_an_original_database_owned_view(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    context = prepared(case)
    no_native_io(case, monkeypatch)
    case["db"].db.conn.execute("BEGIN")
    try:
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)
    finally:
        case["db"].db.conn.rollback()


def test_context_garbage_collection_releases_no_original_order_or_database_state(prepare_case):
    case, api = prepare_case, context_api()
    before = len(api._PREPARED)
    changes = case["db"].db.conn.total_changes
    context = prepared(case)
    ref = weakref.ref(context)
    assert len(api._PREPARED) == before+1
    del context
    gc.collect()
    assert ref() is None and len(api._PREPARED) == before
    assert case["db"].db.conn.total_changes == changes
    assert case["db"].get_order_history(case["key"])["attempts"] == []


def test_legitimate_intent_does_not_turn_the_pre_intent_context_into_a_claim_exception(prepare_case, monkeypatch):
    from CustomBuySellPoint.Decision import canonical_bytes
    case, api = prepare_case, context_api()
    context = prepared(case)
    payload = json.loads(api._PREPARED[context][1])["payload"]
    assert case["db"].acquire_open_intent(case["key"], requested_qty=payload["quantity"], client_order_id="contextIntent",
        position_side=payload["order_contract"]["execution"]["position_side"],
        order_contract=payload["order_contract"],
        snapshot={"price": 100, "opening_inputs": payload["opening_inputs"]})
    before = case["db"].get_record(case["key"])
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)
    assert case["db"].get_record(case["key"]) == before
    assert before["open_attempt"] == 1 and before["open_order_status"] == "created"
    del context
    gc.collect()
    assert case["db"].get_record(case["key"]) == before


def test_original_sticky_failure_is_rechecked_without_private_profile_reads(prepare_case, monkeypatch):
    case, api = prepare_case, context_api()
    context = prepared(case)
    account = json.loads(api._PREPARED[context][1])["payload"]["order_contract"]["account_context"]
    case["db"].reconcile_account(account_context=account, before_id="0"*64, after_id="1"*64, wallet_ids=[], execution_scan_ids=[])
    assert case["db"].get_account_risk_state(account)["frozen"] is True
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)
    assert case["db"].get_account_risk_state(account)["frozen"] is True


@pytest.mark.parametrize("damage", ["record", "candidate", "kill"])
def test_original_risk_reader_callback_cannot_leave_a_final_local_change_unchecked(prepare_case, monkeypatch, damage):
    case, api = prepare_case, context_api()
    context = prepared(case)
    original = case["db"].assert_account_new_risk_allowed
    def changed(account):
        original(account)
        if damage == "record":
            case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='risk callback changed record' WHERE id=?", (case["key"],))
        elif damage == "candidate":
            path = Path(case["trade"].safety_policy.strategy_receipt["path"])
            path.write_bytes(path.read_bytes()+b"\n ")
        else:
            case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    monkeypatch.setattr(case["db"], "assert_account_new_risk_allowed", changed)
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)


@pytest.mark.parametrize("method", ["prepare_order", "check", "assert_order_allowed"])
def test_replacing_loaded_prepare_dependencies_after_capture_fails_without_invoking_them(prepare_case, monkeypatch, method):
    case, api = prepare_case, context_api()
    context = prepared(case)
    target = case["trade"] if method == "prepare_order" else case["guard"] if method == "check" else case["trade"].safety_policy
    monkeypatch.setattr(type(target), method, lambda *args, **kwargs: pytest.fail("replaced runtime was invoked"))
    no_native_io(case, monkeypatch)
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            api.assert_native_prepare_context_current(case["trade"], context)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(m, s) for m in ("one_way", "hedged") for s in (True, False)])
def test_nonempty_native_account_sources_and_original_risk_reader_stay_no_get_in_cas(store, tmp_path, monkeypatch, venue, mode, side):
    from .native_order_preparation_case import CODES, native_order_case
    from Trade.NativeInstrumentCurrent import collect_native_instruments_for_engine
    from Trade.NativeComponentCollector import collect_and_check_native_components
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue, mode=mode, side=side)
    api = context_api()
    context = api._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    collect_native_instruments_for_engine(case["trade"], CODES, max_age_ms=2000, max_observation_span_ms=2000)
    components = collect_and_check_native_components(db, case["client"], mode="testnet", markets=case["units"],
        before_id=case["before_id"], account_scope="native-context-fixture", policy=case["policy"])
    no_native_io(case, monkeypatch)
    for name in {row[0] for row in case["trace"]}:
        monkeypatch.setattr(case["client"], name, lambda *args, **kwargs: pytest.fail("no native GET inside CAS"))
    before, changes = db.db.query("SELECT * FROM chan_trade"), db.db.conn.total_changes
    with db.db.transaction():
        assert api.assert_native_prepare_context_current(case["trade"], context) is None
    assert db.db.query("SELECT * FROM chan_trade") == before and db.db.conn.total_changes == changes
    assert components["payload"]["economics_complete"] is components["payload"]["native_admission_verified"] is False
