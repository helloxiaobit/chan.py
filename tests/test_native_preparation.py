"""Actual original input guard/Engine prepare; synthetic config and fake I/O."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Decision import canonical_bytes, read_decision
from CustomBuySellPoint.Signal import CSignal
from OfflineData.offline_data_util import CKLineDB
from Trade.Script.OpeningInputs import COpeningInputs
from .test_crypto_venue_parameters import venue_engine
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_deployment_workflow import deployment_model


HOUR = 3_600_000
NOW = 24*HOUR
CODES = ["TEST/USDT:USDT", "ALT/USDT:USDT"]


def preparation_api():
    assert importlib.util.find_spec("Trade.NativePreparation") is not None, "actual native prepare identity boundary is missing"
    from Trade import NativePreparation
    return NativePreparation


def test_native_preparation_api_exists():
    assert callable(preparation_api().capture_native_prepare_identity)


@pytest.fixture(params=[(v, m, s) for v in ("binance", "okx") for m in ("one_way", "hedged") for s in (True, False)])
def prepare_case(request, store, tmp_path, monkeypatch):
    db, conf = store
    venue, mode, side = request.param
    api = preparation_api()
    trade = venue_engine(db, tmp_path, venue, mode)
    market_path = tmp_path/"prepare-bars.db"
    source = dict(exchange=venue, market_type="swap", settle="USDT", price_type="contract")
    with CKLineDB(str(market_path)) as market:
        market.bind_source(source)
        for code in CODES:
            for level, interval in ((KL_TYPE.K_4H, 4*HOUR), (KL_TYPE.K_60M, HOUR)):
                market.upsert_klines(code, level, [(at, 100, 101, 99, 100, 1) for at in range(0, NOW, interval)])
    configuration = {"db": conf, "offline_data": {"sqlite_path": str(market_path), "source_identity": source},
                     "ccxt": copy.deepcopy(trade.ccxt_conf), "trade": {"code_list": CODES, "lv_list": ["K_4H", "K_60M"],
                         "strategy": "multi_lv", "strategy_receipt": trade.safety_policy.strategy_receipt["path"]},
                     "notify": {"backend": "none"}}
    config_path = tmp_path/"native-prepare.json"
    config_path.write_bytes(canonical_bytes(configuration))
    clock = {"now": NOW}
    guard = COpeningInputs(config_path, now_ms=lambda: clock["now"])
    trade.opening_inputs = guard
    unit = make_crypto_klu([NOW-HOUR, 100, 101, 99, 100, 1], KL_TYPE.K_60M, NOW)
    unit.source_identity = source
    signal = CSignal(CODES[0], KL_TYPE.K_60M, side, "1", unit, 100, sl_thred=90, target_klu_time=unit.time)
    signal.freeze_decision()
    key = db.add_signal(signal)
    monkeypatch.setattr(api, "utc_now_ms", lambda: clock["now"])
    return {"api": api, "db": db, "trade": trade, "key": key, "clock": clock, "guard": guard,
            "config": config_path, "market": market_path, "source": source}


def capture(case, **options):
    return case["api"].capture_native_prepare_identity(case["trade"], case["key"], 0.037, 100, **options)


def test_actual_inputs_candidate_signal_and_prepared_terms_are_bound_without_intent_or_send(prepare_case):
    case = prepare_case
    db, engine = case["db"], case["trade"]
    before, changes = db.get_record(case["key"]), db.db.conn.total_changes
    document = capture(case, post_only=True)
    assert document["schema"] == "chan-native-prepare-identity-v1"
    p = document["payload"]
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["coverage"] == "actual_local_prepare_identity_only"
    assert p["record_sha256"] == hashlib.sha256(canonical_bytes(before)).hexdigest()
    assert p["opening_inputs"]["signal_event_id"] == read_decision(before["signal_decision"].encode())["event_id"]
    assert p["opening_inputs"]["inputs_sha256"] == case["guard"].snapshot()["inputs_sha256"]
    assert p["order_contract"]["schema"] == "chan-ccxt-order-v3"
    assert p["order_contract"]["quantity"] == "0.03"
    assert p["order_contract"]["exchange_amount"] == "3"
    assert p["order_contract"]["post_only"] is True
    assert p["request"] == {"record_id": case["key"], "amount": 0.037, "price": 100, "post_only": True}
    assert p["candidate"]["status"] == "candidate"
    assert p["runtime"]["coverage"] == "selected_prepare_callables"
    assert p["runtime"]["callables"]
    assert db.get_record(case["key"]) == before and db.db.conn.total_changes == changes
    assert db.get_order_history(case["key"])["attempts"] == []
    assert engine.exchange.created == [] and engine.exchange.leverage_calls == []
    raw = canonical_bytes(document)
    assert b'"api_key"' not in raw and b'"secret"' not in raw


@pytest.mark.parametrize("damage", ["config", "bars", "signal", "candidate", "candidate_extra", "kill", "unlock", "engine_config", "scope"])
def test_mutation_during_real_private_prepare_is_not_frozen_as_a_success(prepare_case, monkeypatch, damage):
    case = prepare_case
    engine, db = case["trade"], case["db"]
    method = engine.exchange.fetch_leverage
    touched = []
    def changed(*args, **kwargs):
        result = method(*args, **kwargs)
        if not touched:
            touched.append(1)
            if damage == "config":
                case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
            elif damage == "bars":
                with CKLineDB(str(case["market"])) as market:
                    market.conn.execute("UPDATE kline SET v=9 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[1], HOUR))
                    market.conn.commit()
            elif damage == "signal":
                db.db.execute(f"UPDATE {db.table} SET sl_thred=95 WHERE id=?", (case["key"],))
            elif damage in {"candidate", "candidate_extra"}:
                from pathlib import Path
                path = Path(engine.safety_policy.strategy_receipt["path"])
                document = json.loads(path.read_bytes())
                document["status" if damage == "candidate" else "new_observation"] = "rejected" if damage == "candidate" else "changed"
                path.write_bytes(canonical_bytes(document))
            elif damage == "kill":
                engine.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
            elif damage == "unlock":
                engine.safety_policy.environ.pop("CHANPY_ENABLE_TESTNET")
            elif damage == "engine_config":
                engine.ccxt_conf["leverage"] = 4
            else:
                case["guard"]._scope["code_list"] = [CODES[0]]
        return result
    monkeypatch.setattr(engine.exchange, "fetch_leverage", changed)
    with pytest.raises(CChanException):
        capture(case)
    assert touched == [1]
    assert db.get_record(case["key"])["open_attempt"] == 0
    assert db.get_order_history(case["key"])["attempts"] == []
    assert engine.exchange.created == []


@pytest.mark.parametrize("target", ["engine_instance", "engine_class", "engine_accessor", "guard_instance", "guard_class", "guard_defaults", "policy_class"])
def test_file_hash_cannot_hide_replaced_loaded_callables_or_defaults(prepare_case, monkeypatch, target):
    case = prepare_case
    engine, guard = case["trade"], case["guard"]
    if target == "engine_instance":
        monkeypatch.setattr(engine, "prepare_order", lambda *args, **kwargs: pytest.fail("must not call replaced prepare"))
    elif target == "engine_class":
        monkeypatch.setattr(type(engine), "prepare_order", lambda *args, **kwargs: pytest.fail("must not call replaced class prepare"))
    elif target == "engine_accessor":
        original = engine.get_exchange
        # Even an equivalent forwarding accessor is not the pinned original.
        monkeypatch.setattr(engine, "get_exchange", lambda: original())
    elif target == "guard_instance":
        monkeypatch.setattr(guard, "check", lambda *args, **kwargs: {"passed": True})
    elif target == "guard_class":
        monkeypatch.setattr(type(guard), "assert_current", lambda *args, **kwargs: {"passed": True})
    elif target == "guard_defaults":
        monkeypatch.setattr(type(guard).check, "__kwdefaults__", {"engine": True, "price": None})
    else:
        monkeypatch.setattr(type(engine.safety_policy), "assert_order_allowed", lambda *args: None)
    monkeypatch.setattr(engine.exchange, "fetch_leverage", lambda *args, **kwargs: pytest.fail("invalid loaded runtime reached private read"))
    with pytest.raises(CChanException):
        capture(case)
    assert engine.exchange.created == []


@pytest.mark.parametrize("field", ["receipts", "passed", "check_id", "native_boundary"])
def test_no_caller_evidence_or_approval_argument_can_replace_actual_prepare(prepare_case, field):
    case = prepare_case
    with pytest.raises(TypeError):
        capture(case, **{field: True})
    assert case["trade"].exchange.account_reads == []


def test_owned_database_transaction_is_refused_before_prepare_private_reads(prepare_case, monkeypatch):
    case = prepare_case
    monkeypatch.setattr(case["trade"].exchange, "fetch_leverage", lambda *args, **kwargs: pytest.fail("private I/O under original transaction"))
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            capture(case)
        assert case["db"].db.conn.in_transaction


def test_uninitialized_client_is_refused_without_creating_an_exchange_session(prepare_case, monkeypatch):
    import ccxt
    case = prepare_case
    case["trade"].exchange = None
    monkeypatch.setattr(ccxt, case["trade"].ccxt_conf["exchange"],
                        lambda *args, **kwargs: pytest.fail("identity capture created a new exchange session"))
    with pytest.raises(CChanException):
        capture(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("field,bad", [("amount", True), ("amount", 0), ("amount", float("nan")), ("amount", "0.037"),
    ("price", True), ("price", float("inf")), ("price", -1), ("post_only", 1), ("record_id", True)])
def test_request_is_typed_finite_and_never_coerced_into_new_risk(prepare_case, field, bad):
    case = prepare_case
    values = {"record_id": case["key"], "amount": 0.037, "price": 100, "post_only": False}
    values[field] = bad
    with pytest.raises(CChanException):
        case["api"].capture_native_prepare_identity(case["trade"], **values)
    assert case["trade"].exchange.account_reads == []


def test_private_failure_is_redacted_without_synthetic_candidate_or_order(prepare_case, monkeypatch):
    case = prepare_case
    def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE_PREPARE_KEY_DO_NOT_PRINT")
    monkeypatch.setattr(case["trade"].exchange, "fetch_leverage", failed)
    with pytest.raises(CChanException) as caught:
        capture(case)
    assert "PRIVATE_PREPARE_KEY" not in str(caught.value)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_importing_prepare_boundary_does_not_import_sdk_config_or_optional_models():
    preparation_api()
    script = """
import importlib.abc, sys
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','yaml','numpy','pandas','torch','sklearn','optuna','xgboost','lightgbm','PyQt6','Config'}:
            raise ImportError('not installed')
sys.meta_path.insert(0, NoOptional())
from Trade.NativePreparation import capture_native_prepare_identity
assert callable(capture_native_prepare_identity)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""


@pytest.mark.parametrize("damage", ["record", "config", "candidate"])
def test_final_clock_cannot_mutate_frozen_identity_after_last_input_read(prepare_case, monkeypatch, damage):
    case = prepare_case
    times = []
    def clock():
        times.append(1)
        if len(times) == 2:
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='changed at end' WHERE id=?", (case["key"],))
            elif damage == "config":
                case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
            else:
                from pathlib import Path
                path = Path(case["trade"].safety_policy.strategy_receipt["path"])
                path.write_bytes(path.read_bytes()+b"\n ")
        return case["clock"]["now"]
    monkeypatch.setattr(case["api"], "utc_now_ms", clock)
    with pytest.raises(CChanException):
        capture(case)
    assert times == [1, 1]
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("bad", [None, True, -1, NOW+0.5, 2**63])
def test_invalid_start_clock_is_rejected_before_original_private_prepare(prepare_case, monkeypatch, bad):
    case = prepare_case
    monkeypatch.setattr(case["api"], "utc_now_ms", lambda: bad)
    with pytest.raises(CChanException):
        capture(case)
    assert case["trade"].exchange.account_reads == []


@pytest.mark.parametrize("field", ["database_owner", "exchange_owner", "input_owner", "configuration", "kill"])
def test_final_code_check_cannot_replace_the_original_prepare_owners(prepare_case, monkeypatch, field):
    case = prepare_case
    implementation = case["api"]._implementation
    checked = []
    def changed():
        result = implementation()
        checked.append(1)
        if len(checked) == 5:
            if field == "database_owner":
                case["trade"].chan_db = object()
            elif field == "exchange_owner":
                case["trade"].exchange = object()
            elif field == "input_owner":
                case["trade"].opening_inputs = object()
            elif field == "configuration":
                case["trade"].ccxt_conf["leverage"] = 4
            else:
                case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
        return result
    monkeypatch.setattr(case["api"], "_implementation", changed)
    with pytest.raises(CChanException):
        capture(case)
    assert len(checked) >= 5
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("entry_state", ["valid", "missing", "tampered", "replaced_verifier"])
def test_actual_deployment_and_entry_assessment_are_verified_not_caller_pass_flags(deployment_model, store, tmp_path, monkeypatch, entry_state):
    from Config.EnvConfig import CEnv
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from .test_deployment_workflow import future_candidate
    api = preparation_api()
    db, db_conf = store
    manifest = tmp_path/"native-model-deployment.json"
    publish_deployment(manifest, deployment_model["model"].GetModelPath(), candidate_score=0.0, entry_score=0.0, post_score=0.0)
    deployed = CDeployment(manifest)
    chan, signal = future_candidate(deployment_model)
    now = signal.sig_klu.close_ms+HOUR//4
    deployed.prepare_signal(chan, signal, observed_ms=signal.sig_klu.close_ms)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    key = db.add_signal(signal)
    engine = venue_engine(db, tmp_path, "binance")
    configuration = {"db": db_conf, "offline_data": {"sqlite_path": str(deployment_model["root"]/"kline.db"),
                         "source_identity": deployment_model["source_identity"]}, "ccxt": copy.deepcopy(engine.ccxt_conf),
                     "trade": {"deployment_manifest": str(manifest), "strategy_receipt": engine.safety_policy.strategy_receipt["path"]},
                     "notify": {"backend": "none"}}
    config_path = tmp_path/"native-model-config.json"
    config_path.write_bytes(canonical_bytes(configuration))
    monkeypatch.setattr(CEnv, "_instance", CEnv(str(config_path)))
    engine.opening_inputs = COpeningInputs(config_path, now_ms=lambda: now)
    monkeypatch.setattr(api, "utc_now_ms", lambda: now)
    price = signal.open_thred*(1.001 if signal.is_buy else 0.999)
    assessment = deployed.assess_entry(db.get_record(key), price, observed_ms=now)
    if entry_state == "missing":
        assessment = None
    elif entry_state == "tampered":
        assessment = {**assessment, "score": 0.123, "passed": True}
    elif entry_state == "replaced_verifier":
        from Trade.Script import Deployment
        original = Deployment.verify_entry_assessment
        monkeypatch.setattr(Deployment, "verify_entry_assessment", lambda *args, **kwargs: original(*args, **kwargs))
    if entry_state == "valid":
        result = api.capture_native_prepare_identity(engine, key, 0.037, price, entry_assessment=assessment)
        p = result["payload"]
        assert p["scope"]["deployment_id"] == deployed.deployment_id
        assert p["scope"]["model_artifact_id"] == deployed.model.artifact_id
        assert p["entry_assessment_sha256"] == hashlib.sha256(canonical_bytes(assessment)).hexdigest()
        assert p["native_admission_verified"] is False
    else:
        with pytest.raises(CChanException):
            api.capture_native_prepare_identity(engine, key, 0.037, price, entry_assessment=assessment)
        assert engine.exchange.account_reads == []
    assert db.get_record(key)["open_attempt"] == 0 and engine.exchange.created == []


@pytest.mark.parametrize("target", ["guard_property", "scope_property", "static_limits", "numeric_helper",
                                   "float_helper", "contract_helper", "code_object", "copied_globals"])
def test_selected_prepare_runtime_covers_properties_static_rules_and_loaded_code(prepare_case, monkeypatch, target):
    case = prepare_case
    from Trade import CCXTTradeEngine as engine_module
    if target in {"guard_property", "scope_property"}:
        name = "env" if target == "guard_property" else "scope"
        original = getattr(type(case["guard"]), name).fget
        monkeypatch.setattr(type(case["guard"]), name, property(lambda self: original(self)))
    elif target == "static_limits":
        monkeypatch.setattr(type(case["trade"]), "_check_limits", staticmethod(lambda *args: None))
    elif target in {"numeric_helper", "float_helper", "contract_helper"}:
        name = {"numeric_helper": "_quantity", "float_helper": "_float_exact", "contract_helper": "_contract_id"}[target]
        original = getattr(engine_module, name)
        monkeypatch.setattr(engine_module, name, lambda *args, **kwargs: original(*args, **kwargs))
    elif target == "copied_globals":
        from types import FunctionType
        original = type(case["trade"]).prepare_order
        replacement = FunctionType(original.__code__, dict(original.__globals__), original.__name__, original.__defaults__, original.__closure__)
        replacement.__module__, replacement.__qualname__ = original.__module__, original.__qualname__
        replacement.__kwdefaults__ = original.__kwdefaults__
        monkeypatch.setattr(type(case["trade"]), "prepare_order", replacement)
    else:
        original = type(case["trade"]).prepare_order
        # The same function object and on-disk file cannot conceal new code.
        monkeypatch.setattr(original, "__code__", original.__code__.replace(co_name="changed_loaded_prepare"))
    monkeypatch.setattr(case["trade"].exchange, "fetch_leverage", lambda *args, **kwargs: pytest.fail("replaced local rule reached private read"))
    with pytest.raises(CChanException):
        capture(case)
    assert case["trade"].exchange.created == []
