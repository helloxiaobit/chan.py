"""Native components use original durable checks and sticky account freezes."""
import copy
import hashlib
import importlib.util
import subprocess
import sys
import sqlite3

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_account_components import component_case, components_api
from .test_crypto_order_contract import open_legacy_history
from .test_native_admission_interval import explicit_path_environment
from .test_m6_trade import make_signal


TABLE = "chanpy_account_checks"


def check_api():
    assert importlib.util.find_spec("Trade.NativeAccountCheck") is not None, "native component check publication is missing"
    from Trade import NativeAccountCheck
    return NativeAccountCheck


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def save_sources(db, params):
    return {**{key: value for key, value in params.items() if key not in {"pending_orders", "balance_reservations"}},
            "pending_id": db.store_native_account_observation(params["pending_orders"]),
            "balance_id": db.store_native_account_observation(params["balance_reservations"])}


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def test_nonempty_native_check_uses_original_table_and_rebuilds_after_restart(store, tmp_path, monkeypatch, venue, mode, side):
    check_api()
    db, conf = store
    params, _, trade, key = component_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    expected = components_api()(db, **params)
    request = save_sources(db, params)
    old_order, history = db.get_record(key), db.get_order_history(key)
    check = db.reconcile_native_account(**request)
    p = check["payload"]
    assert check["schema"] == "chan-native-account-check-v1"
    assert p["report"]["payload"]["status"] == "matched_observations"
    assert p["report"]["payload"]["components"] == expected
    assert p["report"]["payload"]["economics_complete"] is p["report"]["payload"]["native_admission_verified"] is False
    check_id = digest(check)
    assert db.get_account_check(check_id) == check
    assert db.reconcile_native_account(**request) == check
    state = db.get_account_risk_state(params["account_context"])
    assert state["frozen"] is state["admission_verified"] is False and state["check_ids"] == [check_id]
    assert db.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 1
    assert db.get_record(key) == old_order and db.get_order_history(key) == history and len(trade.exchange.created) == 3
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_account_check(check_id) == check
    finally:
        reopened.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("failure", ["missing_pending", "missing_balance", "missing_wallet", "native_mismatch", "projection_drift"])
def test_native_failure_publishes_original_sticky_freeze_and_never_gets_cleared_by_match(store, tmp_path, monkeypatch, venue, failure):
    check_api()
    db, conf = store
    from . import test_native_account_components as fixtures
    collect = fixtures.collect_native_balance_reservations
    captured = {}
    def capture(client, **options):
        captured["client"] = client
        return collect(client, **options)
    monkeypatch.setattr(fixtures, "collect_native_balance_reservations", capture)
    params, _, trade, key = component_case(db, tmp_path, monkeypatch, venue)
    request = save_sources(db, params)
    bad = copy.deepcopy(request)
    if failure == "missing_pending":
        bad["pending_id"] = "0"*64
    elif failure == "missing_balance":
        bad["balance_id"] = "0"*64
    elif failure == "missing_wallet":
        bad["wallet_ids"] = []
    elif failure == "native_mismatch":
        # A second raw collection, not a second trade fixture with conflicting
        # execution IDs or a caller-resealed derived document.
        client = captured["client"]
        method = "fapiPrivateV3GetAccount" if venue == "binance" else "privateGetAccountBalance"
        get = getattr(client, method)
        def wrong_margin(options):
            wire = get(options)
            account = wire if venue == "binance" else wire["data"][0]
            asset = account["assets" if venue == "binance" else "details"][0]
            asset["openOrderInitialMargin" if venue == "binance" else "ordFrozen"] = "999"
            return wire
        monkeypatch.setattr(client, method, wrong_margin)
        monkeypatch.setattr("Trade.NativeBalanceReservations.utc_now_ms", lambda: params["balance_reservations"]["payload"]["started_ms"])
        bad["balance_id"] = db.store_native_account_observation(collect(client, mode="testnet"))
    else:
        db.db.execute("UPDATE chan_trade SET current_qty=9 WHERE id=?", (key,))
    failed = db.reconcile_native_account(**bad)
    assert failed["payload"]["report"]["payload"]["status"] in {"mismatch", "incomplete"}
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True
    if failure == "projection_drift":
        db.db.execute("UPDATE chan_trade SET current_qty=? WHERE id=?", (0.02, key))
    matched = db.reconcile_native_account(**request)
    assert matched["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert db.get_account_check(digest(matched)) == matched
    state = db.get_account_risk_state(params["account_context"])
    assert state["frozen"] is True and digest(failed) in state["check_ids"] and digest(matched) in state["check_ids"]
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_account_risk_state(params["account_context"])["frozen"] is True
    finally:
        reopened.close()
    # Same original risk gate, no new state machine or caller override.
    new_key = db.add_signal(make_signal(code="TEST/USDT:USDT", is_buy=False))
    with pytest.raises(CChanException):
        trade.prepare_order("TEST/USDT:USDT", 0.03, 100)
    assert db.get_order_history(new_key)["attempts"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_old_v1_failure_and_native_match_share_the_original_sticky_key(store, tmp_path, monkeypatch, venue):
    check_api()
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    old = db.reconcile_account(**{key: value for key, value in params.items() if key not in {"pending_orders", "balance_reservations"}})
    assert old["schema"] == "chan-account-check-v1" and old["payload"]["report"]["payload"]["status"] == "incomplete"
    native = db.reconcile_native_account(**save_sources(db, params))
    assert native["payload"]["report"]["payload"]["status"] == "matched_observations"
    state = db.get_account_risk_state(params["account_context"])
    assert state["frozen"] is True and len(state["check_ids"]) == 2
    assert db.get_account_check(digest(old)) == old


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_historical_native_check_uses_saved_prefix_not_later_ledger(store, tmp_path, monkeypatch, venue):
    check_api()
    db, conf = store
    params, _, trade, key = component_case(db, tmp_path, monkeypatch, venue)
    check = db.reconcile_native_account(**save_sources(db, params))
    trade.exchange.fill, trade.exchange.status = 2, "closed"
    trade.cover_trade(db.get_record(key), 111, "later interval")
    assert db.get_record(key)["current_qty"] == 0
    assert db.get_account_check(digest(check)) == check
    assert db.get_account_risk_state(params["account_context"])["frozen"] is False
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_account_check(digest(check)) == check
    finally:
        reopened.close()


@pytest.mark.parametrize("damage", ["source_ids", "saved_event", "omit_attempt", "saved_quantity", "metadata"])
def test_resealed_native_check_is_rebuilt_from_original_sources_and_complete_journal_prefix(store, tmp_path, monkeypatch, damage):
    check_api()
    from Trade.AccountRiskStore import SCHEMA
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, "binance")
    check = db.reconcile_native_account(**save_sources(db, params))
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    if damage == "metadata":
        db.db.execute(f"UPDATE {TABLE} SET account_key=?", ("0"*64,))
    else:
        if damage == "source_ids":
            check["payload"]["source_ids"]["pending"] = "0"*64
        elif damage == "saved_event":
            check["payload"]["inputs"]["histories"][0]["attempts"][0]["events"][0]["observed_ms"] -= 1
        elif damage == "omit_attempt":
            check["payload"]["inputs"]["histories"].pop()
        else:
            check["payload"]["inputs"]["projections"][0]["current_qty"] = 9
        check["payload_sha256"] = digest(check["payload"])
        raw, check_id = canonical_bytes(check).decode(), digest(check)
        db.db.execute(f"UPDATE {TABLE} SET check_id=?,payload=?,payload_sha256=?", (check_id, raw, check_id))
    db.db.execute(SCHEMA[f"{TABLE}_no_update"])
    with pytest.raises(CChanException):
        db.get_account_risk_state(params["account_context"])


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "REPLACE"])
def test_native_check_uses_original_append_only_guards(store, tmp_path, monkeypatch, verb):
    check_api()
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, "binance")
    check = db.reconcile_native_account(**save_sources(db, params))
    sql = f"DELETE FROM {TABLE}" if verb == "DELETE" else f"UPDATE {TABLE} SET observed_ms=0" if verb == "UPDATE" else f"INSERT OR REPLACE INTO {TABLE} SELECT * FROM {TABLE}"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(sql)
    assert db.get_account_check(digest(check)) == check


def test_failed_publication_rolls_back_check_without_order_side_effects(store, tmp_path, monkeypatch):
    check_api()
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, "binance")
    request = save_sources(db, params)
    original = db.db.query("SELECT * FROM chan_trade")
    db.db.execute(f"CREATE TRIGGER fail_native_check BEFORE INSERT ON {TABLE} BEGIN SELECT RAISE(ABORT,'PRIVATE_ERROR'); END")
    with pytest.raises(CChanException) as caught:
        db.reconcile_native_account(**request)
    assert "PRIVATE_ERROR" not in str(caught.value)
    assert db.db.query(f"SELECT * FROM {TABLE}") == [] and db.db.query("SELECT * FROM chan_trade") == original
    assert not db.db.conn.in_transaction


def test_native_check_uses_original_nested_savepoint_ownership(store, tmp_path, monkeypatch):
    check_api()
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, "binance")
    request = save_sources(db, params)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with db.db.transaction():
            check = db.reconcile_native_account(**request)
            assert db.get_account_check(digest(check)) == check and db.db.conn.in_transaction
            raise RuntimeError("outer rollback")
    assert db.db.query(f"SELECT * FROM {TABLE}") == [] and not db.db.conn.in_transaction


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_another_connection_native_freeze_between_claim_and_http_blocks_send_and_keeps_reduction(store, tmp_path, monkeypatch, venue):
    check_api()
    db, conf = store
    params, _, trade, held_key = component_case(db, tmp_path, monkeypatch, venue)
    request = save_sources(db, params)
    other = CChanDB(db_conf=conf)
    key = db.add_signal(make_signal(code="TEST/USDT:USDT", is_buy=False))
    created, claim = len(trade.exchange.created), db.claim_order_submission
    def freeze_after_claim(record_id, phase):
        result = claim(record_id, phase)
        other.reconcile_native_account(**{**request, "wallet_ids": []})
        return result
    monkeypatch.setattr(db, "claim_order_submission", freeze_after_claim)
    try:
        with pytest.raises(CChanException):
            open_legacy_history(trade, db.get_record(key), 100)
        assert db.get_record(key)["open_order_status"] == "submitting"
        assert db.get_record(key)["open_attempt"] == 1 and db.get_record(key)["open_order_id"] is None
        assert db.get_account_risk_state(params["account_context"])["frozen"] is True
        trade.restore()
        assert len(trade.exchange.created) == created and db.get_record(key)["open_attempt"] == 1
        monkeypatch.setattr(db, "claim_order_submission", claim)
        trade.exchange.fill, trade.exchange.status = 2, "closed"
        trade.cover_trade(db.get_record(held_key), 111, "native-frozen risk reduction")
        assert db.get_record(held_key)["current_qty"] == 0
        assert db.get_account_risk_state(params["account_context"])["frozen"] is True
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_native_check_rebuilds_in_core_only_process_without_optional_sdk_or_yaml(store, tmp_path, monkeypatch, venue):
    check_api()
    db, conf = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    check = db.reconcile_native_account(**save_sources(db, params))
    code = """
import importlib.abc, json, sys
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','yaml','torch','xgboost','sklearn','optuna','PyQt6','minio','PIL'}:
            attempted.append(fullname)
            raise ImportError('optional dependency blocked')
sys.meta_path.insert(0, BlockOptional())
from Config.EnvConfig import CEnv
from Trade.db_util import CChanDB
data = json.loads(sys.stdin.buffer.read())
env = CEnv.__new__(CEnv)
env.conf = {}
CEnv._instance = env
db = CChanDB(db_conf=data['db'])
try:
    changes = db.db.conn.total_changes
    assert db.get_account_check(data['check_id']) == data['check']
    assert db.get_account_risk_state(data['context'])['frozen'] is False
    assert db.db.conn.total_changes == changes and not db.db.conn.in_transaction
finally:
    db.close()
assert not attempted, attempted
"""
    result = subprocess.run([sys.executable, "-c", code],
        input=canonical_bytes({"db": conf, "check_id": digest(check), "check": check, "context": params["account_context"]}),
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert not result.stderr


def test_complete_journal_prefix_cannot_be_omitted_by_rebuilding_a_plausible_component_report(store, tmp_path, monkeypatch):
    api = check_api()
    from Trade.AccountRiskStore import SCHEMA
    db, conf = store
    params, inputs, trade, _ = component_case(db, tmp_path, monkeypatch, "binance")
    old_clock = inputs["before"]["payload"]["started_ms"]-100
    for module in ("Trade.OrderAudit", "Trade.db_util"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: old_clock)
    other = CChanDB(db_conf=conf, table_name="zero_fill_attempts")
    try:
        key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        quantity, _, contract = trade.prepare_order("TEST/USDT:USDT", 0.03, 100, record=other.get_record(key))
        assert other.acquire_open_intent(key, quantity, "cpZeroCanceled", order_contract=contract)
        assert other.claim_order_submission(key, "open")
        other.record_order_ack(key, "open", "901", client_order_id="cpZeroCanceled", expected_attempt=1)
        other.apply_open_fill(key, 0, None, "canceled", order_id="901", client_order_id="cpZeroCanceled", expected_attempt=1)
    finally:
        other.close()
    check = db.reconcile_native_account(**save_sources(db, params))
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    saved = check["payload"]["inputs"]
    saved["histories"] = [history for history in saved["histories"] if history["attempts"][0]["identity"]["trade_table"] != "zero_fill_attempts"]
    saved["projections"] = [projection for projection in saved["projections"] if projection["trade_table"] != "zero_fill_attempts"]
    # New hashes and a freshly recomputed *matching* financial result alone
    # cannot substitute for all original journal attempts at that boundary.
    check["payload"]["report"] = api._report(params["account_context"], check["payload"]["source_ids"], saved)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    check["payload_sha256"] = digest(check["payload"])
    raw, key = canonical_bytes(check).decode(), digest(check)
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    db.db.execute(f"UPDATE {TABLE} SET check_id=?,payload=?,payload_sha256=?", (key, raw, key))
    db.db.execute(SCHEMA[f"{TABLE}_no_update"])
    with pytest.raises(CChanException):
        db.get_account_check(key)
