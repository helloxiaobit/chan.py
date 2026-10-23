"""One real prepare/source invocation bound by the original diagnostic CAS."""
import importlib.util
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from contextlib import closing

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.db_util import CChanDB
from .native_order_preparation_case import native_order_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment


def prepared_api():
    assert importlib.util.find_spec("Trade.NativePreparedIntent") is not None, "source-owned original prepared CAS is missing"
    from Trade import NativePreparedIntent
    return NativePreparedIntent


def test_source_owned_prepared_intent_api_exists():
    assert callable(prepared_api().acquire_native_prepared_diagnostic_intent)


def acquire(case, **changes):
    arguments = {"before_id": case["before_id"], "account_scope": "prepared-native-fixture", "policy": case["policy"],
                 "instrument_max_age_ms": 2000, "instrument_max_observation_span_ms": 2000,
                 "client_order_id": "preparedNativeIntent"}
    arguments.update(changes)
    return prepared_api().acquire_native_prepared_diagnostic_intent(case["trade"], case["key"], .1, 100, **arguments)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(m, s) for m in ("one_way", "hedged") for s in (True, False)])
def test_actual_nonempty_sources_and_preparation_are_persisted_inside_original_cas(store, tmp_path, monkeypatch, venue, mode, side):
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue, mode=mode, side=side)
    monkeypatch.setattr("Trade.NativePreparedIntent.utc_now_ms", lambda: case["clock"]["now"])
    old = [db.get_record(key) for key in case["history_keys"]]
    assert acquire(case) is True
    after = db.get_record(case["key"])
    assert after["open_attempt"] == 1 and after["open_order_status"] == "created"
    transition = read_native_order_transition(db, case["key"])
    assert transition["schema"] == "chan-native-order-transition-v2"
    p = transition["payload"]
    binding = p["root"]["preparation"]
    assert binding["schema"] == "chan-native-prepared-intent-binding-v1"
    assert binding["identity"]["payload"]["request"]["record_id"] == case["key"]
    assert binding["components"]["payload"]["check_id"] == p["boundary"]["payload"]["check_id"]
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert [db.get_record(key) for key in case["history_keys"]] == old
    assert len(case["created"]) == 3
    # Persisting consistency is not sufficient funding or permission to claim.
    with pytest.raises(CChanException):
        db.claim_order_submission(case["key"], "open")
    assert db.get_record(case["key"]) == after


def make_case(store, tmp_path, monkeypatch, venue):
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue)
    monkeypatch.setattr("Trade.NativePreparedIntent.utc_now_ms", lambda: case["clock"]["now"])
    return case


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["candidate", "cash", "pending", "foreign_row"])
def test_source_time_changes_stop_original_intent_without_overwriting_them(store, tmp_path, monkeypatch, venue, damage):
    case = make_case(store, tmp_path, monkeypatch, venue)
    db = case["db"]
    name = (("fapiPrivateGetOpenOrders" if venue == "binance" else "privateGetTradeOrdersPending") if damage in {"cash", "pending"}
            else ("fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice"))
    original = getattr(case["client"], name)
    touched = []
    def changed(params):
        if not touched:
            touched.append(1)
            if damage == "candidate":
                path = Path(case["trade"].safety_policy.strategy_receipt["path"])
                path.write_bytes(path.read_bytes()+b"\n ")
            elif damage == "cash":
                asset = case["account_raw"]["assets" if venue == "binance" else "details"][0]
                asset["walletBalance" if venue == "binance" else "cashBal"] = "1001"
            elif damage == "pending":
                case["pending_raw"]["executedQty" if venue == "binance" else "accFillSz"] = ".4" if venue == "binance" else "4"
            else:
                with closing(CChanDB(db_conf=store[1])) as other:
                    other.db.execute(f"UPDATE {other.table} SET unwatch_reason='foreign source-time change' WHERE id=?", (case["history_keys"][0],))
        return original(params)
    monkeypatch.setattr(case["client"], name, changed)
    with pytest.raises(CChanException):
        acquire(case)
    assert touched == [1]
    assert db.get_record(case["key"])["open_attempt"] == 0
    assert db.get_order_history(case["key"])["attempts"] == []
    assert db.get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is True
    if damage == "foreign_row":
        assert db.get_record(case["history_keys"][0])["unwatch_reason"] == "foreign source-time change"


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("stage", ["sql", "reference", "reference_delay", "forged_context"])
def test_original_cas_and_binding_roll_back_together_on_publication_or_freshness_failure(store, tmp_path, monkeypatch, venue, stage):
    case = make_case(store, tmp_path, monkeypatch, venue)
    db = case["db"]
    for values in (case["policy"]["max_age_ms"], case["policy"]["max_observation_span_ms"]):
        for key in values:
            values[key] = 10000
    case["policy"]["max_source_skew_ms"] = 10000
    execute = db.db.execute
    def failed(sql, params=()):
        if sql.startswith("UPDATE "+db.table+" SET status='submitted'") and stage == "sql":
            raise RuntimeError("PRIVATE_SQL_EXCEPTION_DO_NOT_EXPOSE")
        if sql.startswith("INSERT INTO chanpy_native_order_transitions"):
            if stage == "reference":
                raise RuntimeError("PRIVATE_REFERENCE_EXCEPTION_DO_NOT_EXPOSE")
            result = execute(sql, params)
            if stage == "reference_delay":
                case["clock"]["now"] += 1001
            return result
        return execute(sql, params)
    monkeypatch.setattr(db.db, "execute", failed)
    if stage == "forged_context":
        write = db._order_write
        def forged(*args, **kwargs):
            kwargs["native_preparation"] = {"passed": True}
            return write(*args, **kwargs)
        monkeypatch.setattr(db, "_order_write", forged)
    with pytest.raises(CChanException) as caught:
        acquire(case, instrument_max_age_ms=1000)
    assert "PRIVATE_" not in str(caught.value)
    assert db.get_record(case["key"])["open_attempt"] == 0
    assert db.get_order_history(case["key"])["attempts"] == []
    assert db.db.query("SELECT * FROM chanpy_native_order_transitions") == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_restart_reads_original_binding_without_a_client_or_repreparing_and_claim_stays_locked(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    expected = read_native_order_transition(case["db"], case["key"])
    monkeypatch.setattr("Trade.NativePreparation._capture_native_prepare_context", lambda *a, **k: pytest.fail("historical read must not prepare"))
    monkeypatch.setattr(case["client"], "request", lambda *a, **k: pytest.fail("historical read must not request"))
    with closing(CChanDB(db_conf=store[1])) as restarted:
        before = restarted.get_record(case["key"])
        assert read_native_order_transition(restarted, case["key"]) == expected
        with pytest.raises(CChanException):
            restarted.claim_order_submission(case["key"], "open")
        assert restarted.get_record(case["key"]) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_other_record_change_during_after_cas_local_check_cannot_escape_the_final_ledger_check(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    db = case["db"]
    original = db.assert_account_new_risk_allowed
    touched = []
    def changed(account):
        original(account)
        if db.get_record(case["key"])["open_attempt"] and not touched:
            touched.append(1)
            db.db.execute(f"UPDATE {db.table} SET unwatch_reason='late local callback' WHERE id=?", (case["history_keys"][0],))
    monkeypatch.setattr(db, "assert_account_new_risk_allowed", changed)
    with pytest.raises(CChanException):
        acquire(case)
    assert touched == [1]
    assert db.get_record(case["key"])["open_attempt"] == 0
    assert db.get_record(case["history_keys"][0])["unwatch_reason"] is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_unobserved_later_server_change_does_not_turn_coherent_history_into_claim_permission(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    name = "fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice"
    original = getattr(case["client"], name)
    def changed(params):
        result = original(params)
        asset = case["account_raw"]["assets" if venue == "binance" else "details"][0]
        asset["walletBalance" if venue == "binance" else "cashBal"] = "1001"
        return result
    monkeypatch.setattr(case["client"], name, changed)
    assert acquire(case)
    stored = read_native_order_transition(case["db"], case["key"])
    assert stored["payload"]["native_admission_verified"] is False
    with pytest.raises(CChanException):
        case["db"].claim_order_submission(case["key"], "open")


@pytest.mark.parametrize("damage", ["record", "quantity", "contract", "scope", "check", "market", "clock", "entry",
                                    "identity_extra", "post_only_alias", "rounded_price", "scope_source", "policy_alias",
                                    "component_extra", "component_top_extra", "operation_order"])
def test_independent_stored_links_reject_resealed_preparation_fields(store, tmp_path, monkeypatch, damage):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    assert acquire(case)
    document = read_native_order_transition(case["db"], case["key"])
    root = copy.deepcopy(document["payload"]["root"])
    binding = root["preparation"]
    p = binding["identity"]["payload"]
    if damage == "record":
        p["record_sha256"] = "0"*64
    elif damage == "quantity":
        p["quantity"] = .2
    elif damage == "contract":
        p["order_contract"]["notional"] = "20"
    elif damage == "scope":
        p["scope"]["code_list"] = p["scope"]["code_list"][:1]
    elif damage == "check":
        binding["components"]["payload"]["check_id"] = "0"*64
    elif damage == "market":
        binding["components"]["payload"]["market_evidence"]["payload"]["observations"] = []
    elif damage == "clock":
        binding["finished_ms"] = p["started_ms"]-1
    elif damage == "entry":
        binding["entry_assessment"] = {"passed": True}
    elif damage == "identity_extra":
        p["unchecked_extra"] = "must not be adopted"
    elif damage == "post_only_alias":
        p["request"]["post_only"] = 0
    elif damage == "rounded_price":
        p["price"] = 99.0
    elif damage == "scope_source":
        p["scope"]["source"]["price_type"] = "mark"
    elif damage == "policy_alias":
        binding["components"]["payload"]["policy"]["max_age_ms"]["account"] = 2000.0
    elif damage == "component_extra":
        binding["components"]["payload"]["passed"] = True
    elif damage == "component_top_extra":
        binding["components"]["passed"] = True
    else:
        binding["components"]["payload"]["operations"] = list(reversed(binding["components"]["payload"]["operations"]))
    binding["identity"]["payload_sha256"] = hashlib.sha256(canonical_bytes(p)).hexdigest()
    binding["components"]["payload_sha256"] = hashlib.sha256(canonical_bytes(binding["components"]["payload"])).hexdigest()
    attempt = case["db"].get_order_history(case["key"])["attempts"][0]
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            prepared_api().validate_stored_preparation(case["db"], root, attempt)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_known_sticky_failure_rejects_before_any_new_source_get(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    account = case["before"]["payload"]["account_context"]
    case["db"].reconcile_account(account_context=account, before_id="0"*64, after_id="1"*64, wallet_ids=[], execution_scan_ids=[])
    assert case["db"].get_account_risk_state(account)["frozen"] is True
    identity = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    for name in (identity, "fetch_position_mode", "fetch_leverage"):
        monkeypatch.setattr(case["client"], name, lambda *a, **k: pytest.fail("already frozen account made a new source GET"))
    with pytest.raises(CChanException):
        acquire(case)
    assert case["trace"] == []
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_implementation_identity_is_frozen_before_the_first_source_read(store, tmp_path, monkeypatch, venue):
    case = make_case(store, tmp_path, monkeypatch, venue)
    api = prepared_api()
    original = api._implementation
    def changed():
        result = original()
        if case["trace"]:
            result["Trade/NativePreparedIntent.py"] = "0"*64
        return result
    monkeypatch.setattr(api, "_implementation", changed)
    with pytest.raises(CChanException):
        acquire(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_binance_keeps_original_supported_client_id_characters(store, tmp_path, monkeypatch):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    assert acquire(case, client_order_id="cp.test-native:1")
    assert case["db"].get_record(case["key"])["open_client_order_id"] == "cp.test-native:1"


def test_invalid_call_start_clock_rejects_before_reading_native_account(store, tmp_path, monkeypatch):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    monkeypatch.setattr(prepared_api(), "utc_now_ms", lambda: None)
    monkeypatch.setattr(case["client"], "fapiPrivateV3GetBalance", lambda *a, **k: pytest.fail("invalid call clock reached private account read"))
    with pytest.raises(CChanException):
        acquire(case)
    assert case["trace"] == []


@pytest.mark.parametrize("field", ["receipts", "check_id", "passed", "native_preparation"])
def test_entry_does_not_accept_caller_source_receipts_or_approval_packets(store, tmp_path, monkeypatch, field):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    with pytest.raises(TypeError):
        acquire(case, **{field: True})
    assert case["trace"] == []


@pytest.mark.parametrize("field", ["instrument_max_age_ms", "instrument_max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, "2000", 2000.5])
def test_instrument_budget_is_explicit_typed_and_refused_before_io(store, tmp_path, monkeypatch, field, bad):
    case = make_case(store, tmp_path, monkeypatch, "binance")
    with pytest.raises(CChanException):
        acquire(case, **{field: bad})
    assert case["trace"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_first_unobserved_prepared_intent_prevents_a_second_account_intent(store, tmp_path, monkeypatch, venue):
    from Common.CEnum import KL_TYPE
    from Common.KLineTime import make_crypto_klu
    from CustomBuySellPoint.Signal import CSignal
    case = make_case(store, tmp_path, monkeypatch, venue)
    assert acquire(case)
    original_key = case["key"]
    first = case["db"].get_record(original_key)
    signal_body = json.loads(first["signal_decision"])["payload"]["bar"]
    unit = make_crypto_klu([signal_body["open_ms"], 100, 101, 99, 100, 1], KL_TYPE.K_60M, case["clock"]["now"])
    unit.source_identity = {"exchange": venue, "market_type": "swap", "settle": "USDT", "price_type": "contract"}
    signal = CSignal(first["stock_code"], KL_TYPE.K_60M, False, "1", unit, 100, sl_thred=110, target_klu_time=unit.time)
    signal.freeze_decision()
    case["key"] = case["db"].add_signal(signal)
    assert case["key"] != original_key
    with pytest.raises(CChanException):
        acquire(case, client_order_id="secondPreparedIntent")
    assert case["db"].get_record(original_key) == first
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_real_two_symbol_model_entry_is_bound_by_original_cas_not_a_caller_pass(store, tmp_path, monkeypatch, venue):
    from Config.EnvConfig import CEnv
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from Trade.Script.OpeningInputs import COpeningInputs
    from .test_deployment_workflow import deployment_model_data, future_candidates
    from .native_order_preparation_case import CODES, HOUR
    root = tmp_path/"model"
    root.mkdir()
    source = {"exchange": venue, "market_type": "swap", "settle": "USDT", "price_type": "contract"}
    with deployment_model_data(root, source=source, codes=tuple(CODES)) as model:
        manifest = tmp_path/"prepared-deployment.json"
        publish_deployment(manifest, model["model"].GetModelPath(), candidate_score=0.0, entry_score=0.0, post_score=0.0)
        deployed = CDeployment(manifest)
        chan, signal = future_candidates(model, codes=tuple(CODES))[CODES[0]]
        at = signal.sig_klu.close_ms//(4*HOUR)*(4*HOUR)
        case = native_order_case(store[0], store[1], tmp_path, monkeypatch, venue, at_ms=at)
        case["clock"]["now"] = signal.sig_klu.close_ms+HOUR//4
        monkeypatch.setattr(prepared_api(), "utc_now_ms", lambda: case["clock"]["now"])
        deployed.prepare_signal(chan, signal, observed_ms=signal.sig_klu.close_ms)
        chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
        key = store[0].add_signal(signal)
        config = json.loads(case["config"].read_bytes())
        config["offline_data"] = {"sqlite_path": str(root/"kline.db"), "source_identity": source}
        config["trade"]["deployment_manifest"] = str(manifest)
        case["config"].write_bytes(canonical_bytes(config))
        monkeypatch.setattr(CEnv, "_instance", CEnv(str(case["config"])))
        case["trade"].opening_inputs = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"])
        price = signal.open_thred*(1.001 if signal.is_buy else .999)
        assessment = deployed.assess_entry(store[0].get_record(key), price, observed_ms=case["clock"]["now"])
        assert prepared_api().acquire_native_prepared_diagnostic_intent(case["trade"], key, .1, price, before_id=case["before_id"],
            account_scope="prepared-model-fixture", policy=case["policy"], instrument_max_age_ms=2000,
            instrument_max_observation_span_ms=2000, client_order_id="modelPreparedIntent", entry_assessment=assessment)
        stored = read_native_order_transition(store[0], key)["payload"]["root"]["preparation"]
        assert stored["identity"]["payload"]["scope"]["deployment_id"] == deployed.deployment_id
        assert stored["entry_assessment"] == assessment
        assert store[0].get_record(key)["open_order_status"] == "created"
        with pytest.raises(CChanException):
            store[0].claim_order_submission(key, "open")


def test_source_owner_module_import_requires_no_config_sdk_or_optional_models():
    script = """
import importlib.abc, sys
class MissingOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt', 'Config', 'yaml', 'numpy', 'pandas', 'xgboost', 'lightgbm', 'sklearn', 'torch', 'optuna'}:
            raise ImportError('intentionally absent')
sys.meta_path.insert(0, MissingOptional())
from Trade.NativePreparedIntent import acquire_native_prepared_diagnostic_intent
assert callable(acquire_native_prepared_diagnostic_intent)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
