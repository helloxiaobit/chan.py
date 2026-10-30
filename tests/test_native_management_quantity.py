"""Original full-ledger quantity observations, never a portable close permit."""
import copy
from contextlib import closing
from decimal import Decimal

import pytest

from Common.ChanException import CChanException
from Trade import NativeManagement as Management
from Trade import AccountSources as Account
from Trade import NativePendingOrders as Pending
from Trade import db_util as Database
from Trade import OrderAudit as Audit
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.AccountRiskStore import _sha
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.db_util import CChanDB
from .test_crypto_order_contract import open_legacy_history
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_account_components import component_case
from .test_m6_trade import make_signal
from .test_native_pending_orders import regular_row
from .test_native_management_role import configuration


def quantity_api():
    assert hasattr(Management, "observe_native_management_quantity"), "original account/record close-quantity observation is missing"
    return Management.observe_native_management_quantity


@pytest.mark.parametrize("mode,side", [(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def test_exact_record_and_native_leg_quantity_uses_full_original_ledger_without_writes_or_permission(
        store, tmp_path, monkeypatch, mode, side):
    observe = quantity_api()
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance", mode=mode, side=side)
    records = copy.deepcopy(db.db.query(f"SELECT * FROM {db.table} ORDER BY id"))
    histories = [db.get_order_history(row["id"]) for row in records]
    changes = db.db.conn.total_changes
    document = observe(db, key, phase="close", account_snapshot=inputs["after"], pending_orders=params["pending_orders"])
    payload = document["payload"]
    assert document["schema"] == "chan-native-management-quantity-v1" and document["payload_sha256"] == _sha(payload)
    assert payload["local_remaining_quantity"] == "0.02" and payload["native_leg_quantity"] == "0.02"
    assert payload["reserved_record_close_quantity"] == payload["reserved_leg_close_quantity"] == "0"
    assert payload["observed_available_base_quantity"] == "0.02"
    assert payload["new_close_blockers"] == []
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert len(payload["records"]) == len(payload["legs"]) == 2
    assert payload["pending_ownership"]["payload"]["issues"] == []
    assert db.db.conn.total_changes == changes
    assert db.db.query(f"SELECT * FROM {db.table} ORDER BY id") == records
    assert [db.get_order_history(row["id"]) for row in records] == histories


def snapshot_copy(document, change):
    """Rebuild a deliberately supplied raw observation, never source authority."""
    document = copy.deepcopy(document)
    payload = document["payload"]
    change(payload)
    payload.update(Account._snapshot_values(payload["raw"], payload["markets"], payload["account_context"]["venue"]))
    document["payload_sha256"] = _sha(payload)
    Account.verify_account_snapshot(document)
    return document


def native_test_quantity(document, quantity, *, side=True):
    def change(payload):
        signed = quantity if side else -quantity
        row = next(row for row in payload["raw"]["positions"] if row["symbol"] == "TESTUSDT")
        pnl = signed*(Decimal(row["markPrice"])-Decimal(row["entryPrice"]))
        row.update(positionAmt=str(signed), unRealizedProfit=str(pnl), notional=str(signed*Decimal(row["markPrice"])))
        account = payload["raw"]["account"]
        next(row for row in account["positions"] if row["symbol"] == "TESTUSDT").update(positionAmt=str(signed), unrealizedProfit=str(pnl))
        account.update(totalUnrealizedProfit=str(pnl), totalMarginBalance=str(Decimal(account["totalWalletBalance"])+pnl))
        asset = next(row for row in account["assets"] if row["asset"] == "USDT")
        asset.update(unrealizedProfit=str(pnl), marginBalance=str(Decimal(asset["walletBalance"])+pnl))
    return snapshot_copy(document, change)


def pending_copy(document, change, *, at_ms=None):
    document = copy.deepcopy(document)
    payload = document["payload"]
    change(payload)
    for channel in payload["channels"]:
        for page in channel["pages"]:
            page["raw"] = [Pending._raw_order(row, payload["venue"]) for row in page["raw"]]
    if at_ms is not None:
        payload["started_ms"] = payload["finished_ms"] = at_ms
        for channel in payload["channels"]:
            for page in channel["pages"]:
                page.update({key: at_ms for key in ("started_ms", "request_started_ms", "request_finished_ms", "finished_ms")})
    payload["orders"], payload["unsupported_orders"], _ = Pending._derive(payload["channels"], payload["venue"],
        payload["markets"], payload["started_ms"], payload["finished_ms"])
    document["payload_sha256"] = _sha(payload)
    Pending.verify_native_pending_orders(document)
    return document


@pytest.mark.parametrize("damage", ["contract_size", "market_id", "market_symbol"])
def test_independently_valid_account_units_cannot_drift_from_original_order_and_pending_units(store, tmp_path, monkeypatch, damage):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    def change(payload):
        market = next(row for row in payload["markets"] if row["symbol"] == "TEST/USDT:USDT")
        if damage == "contract_size": market["contractSize"] = "0.1"
        elif damage == "market_id": market["id"] = "OTHERUSDT"
        else: market["symbol"] = "OTHER/USDT:USDT"
    try:
        account = snapshot_copy(inputs["after"], change)
    except CChanException:
        assert damage == "market_id"  # Original raw source parser may already reject an unmapped raw row.
        return
    with pytest.raises(CChanException):
        quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=params["pending_orders"])


@pytest.mark.parametrize("quantity", ["0.019999999999999999", "0.020000000000000001"])
def test_valid_native_quantity_difference_has_no_implicit_tolerance(store, tmp_path, monkeypatch, quantity):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    account = native_test_quantity(inputs["after"], Decimal(quantity))
    with pytest.raises(CChanException):
        quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=params["pending_orders"])


def test_partial_open_attempt_does_not_offer_its_current_fill_as_new_close_quantity(store, tmp_path, monkeypatch):
    db, _ = store
    params, inputs, _, _ = component_case(db, tmp_path, monkeypatch, "binance")
    key = next(row["id"] for row in db.db.query(f"SELECT * FROM {db.table}") if row["stock_code"] == "ALT/USDT:USDT")
    payload = quantity_api()(db, key, phase="open", account_snapshot=inputs["after"], pending_orders=params["pending_orders"])["payload"]
    assert payload["local_remaining_quantity"] == "0.3"
    assert payload["observed_available_base_quantity"] == "0" and payload["new_close_blockers"] == ["open_order_not_terminal"]


def test_same_leg_record_in_another_original_table_is_not_ignored_or_borrowed(store, tmp_path, monkeypatch):
    db, conf = store
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, "binance")
    with closing(CChanDB(table_name="other_strategy", db_conf=conf)) as other:
        trade.chan_db = other
        trade.quota_gen = CBenchPriceQuotaGen(10.7)
        trade.exchange.fill, trade.exchange.status = 1, "closed"
        other_key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        open_legacy_history(trade, other.get_record(other_key), 1000)
        trade.chan_db = db
        account = native_test_quantity(inputs["after"], Decimal(".03"))
        account = snapshot_copy(account, lambda p: p.update(finished_ms=Database.utc_now_ms()))
        pending = pending_copy(params["pending_orders"], lambda p: None, at_ms=Database.utc_now_ms())
        payload = quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=pending)["payload"]
        assert payload["native_leg_quantity"] == "0.03"
        assert payload["observed_available_base_quantity"] == "0.02"
        assert len(payload["records"]) == 3 and {r["trade_table"] for r in payload["records"]} == {db.table, other.table}


def test_existing_close_pending_is_counted_once_not_added_twice_or_available_for_new_close(store, tmp_path, monkeypatch):
    db, _ = store
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, "binance")
    current = db.get_record(key)
    amount, price, contract = trade.prepare_order(current["stock_code"], .01, 1000, reduce_only=True, record=current)
    client = "quantityObservedClose2"
    assert db.acquire_close_intent(key, amount, client, "fake existing close", order_contract=contract, previous_attempt=1)
    assert db.claim_order_submission(key, "close")
    db.record_order_ack(key, "close", "703", client_order_id=client, expected_attempt=2)
    db.apply_close_fill(key, 0, None, "open", client_order_id=client, order_id="703", expected_attempt=2)
    current = db.get_record(key)
    row = regular_row("binance", "TESTUSDT", 703)
    row.update(clientOrderId=client, origQty=contract["quantity"], price=contract["price"],
        side="SELL", reduceOnly=True, time=current["cover_intent_ms"], updateTime=current["cover_intent_ms"])
    at_ms = Database.utc_now_ms()
    pending = pending_copy(params["pending_orders"], lambda p: p["channels"][0]["pages"][0]["raw"].append(row), at_ms=at_ms)
    payload = quantity_api()(db, key, phase="close", account_snapshot=inputs["after"], pending_orders=pending)["payload"]
    assert payload["local_remaining_quantity"] == "0.02"
    assert payload["reserved_record_close_quantity"] == payload["reserved_leg_close_quantity"] == "0.01"
    assert payload["observed_available_base_quantity"] == "0" and payload["new_close_blockers"] == ["close_order_not_terminal"]


@pytest.mark.parametrize("damage", ["wrong_direction", "missing_pending", "unowned_pending", "source_hash", "wrong_projection"])
def test_incomplete_or_conflicting_original_quantity_sources_never_become_close_capacity(store, tmp_path, monkeypatch, damage):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    account, pending = inputs["after"], params["pending_orders"]
    original, history, changes = db.get_record(key), db.get_order_history(key), db.db.conn.total_changes
    if damage == "wrong_direction":
        account = native_test_quantity(account, Decimal(".02"), side=False)
    elif damage == "missing_pending":
        pending = pending_copy(pending, lambda p: p["channels"][0]["pages"][0]["raw"].clear())
    elif damage == "unowned_pending":
        def changed(payload):
            payload["channels"][0]["pages"][0]["raw"][0]["clientOrderId"] = "foreign-strategy-client"
        pending = pending_copy(pending, changed)
    elif damage == "source_hash":
        account = copy.deepcopy(account)
        account["payload_sha256"] = "f"*64
    if damage == "wrong_projection":
        with pytest.raises(CChanException):
            with db.db.transaction():
                db.db.execute(f"UPDATE {db.table} SET current_qty=.03 WHERE id=?", (key,))
                quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=pending)
    else:
        with pytest.raises(CChanException):
            quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=pending)
        assert db.db.conn.total_changes == changes
    assert db.get_record(key) == original and db.get_order_history(key) == history


def test_a_future_account_copy_cannot_claim_quantity_before_its_last_original_fill(store, tmp_path, monkeypatch):
    db, conf = store
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, "binance")
    with closing(CChanDB(table_name="later_strategy", db_conf=conf)) as other:
        trade.chan_db = other
        trade.quota_gen = CBenchPriceQuotaGen(10.7)
        trade.exchange.fill, trade.exchange.status = 1, "closed"
        other_key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        open_legacy_history(trade, other.get_record(other_key), 1000)
        trade.chan_db = db
        account = native_test_quantity(inputs["after"], Decimal(".03"))
        pending = pending_copy(params["pending_orders"], lambda p: None, at_ms=Database.utc_now_ms())
        assert account["payload"]["finished_ms"] < other.get_order_history(other_key)["attempts"][0]["events"][-1]["observed_ms"]
        with pytest.raises(CChanException):
            quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=pending)


def test_an_account_market_alias_cannot_disappear_in_a_symbol_dictionary(store, tmp_path, monkeypatch):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    def changed(payload):
        alias = copy.deepcopy(payload["markets"][0])
        alias["id"] = "UNSEENUSDT"
        payload["markets"].insert(0, alias)
    account = snapshot_copy(inputs["after"], changed)
    with pytest.raises(CChanException):
        quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=params["pending_orders"])


def test_dangling_attempt_without_an_event_cannot_vanish_from_full_account_quantity_evidence(store, tmp_path, monkeypatch):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    original = db.get_order_history(key)
    with pytest.raises(CChanException):
        with db.db.transaction():
            db.db.execute(f"INSERT INTO {Audit.ATTEMPTS}(trade_table,record_id,phase,attempt,client_order_id,origin,observed_ms,payload,payload_sha256) "
                f"SELECT trade_table,9999,phase,attempt,'quantityOrphanAttempt',origin,observed_ms,payload,payload_sha256 FROM {Audit.ATTEMPTS} WHERE record_id=? AND phase='open'", (key,))
            quantity_api()(db, key, phase="close", account_snapshot=inputs["after"], pending_orders=params["pending_orders"])
    assert db.get_order_history(key) == original


def test_zero_reported_new_risk_capacity_is_not_a_new_funds_requirement_for_close_quantity(store, tmp_path, monkeypatch):
    db, _ = store
    params, inputs, _, key = component_case(db, tmp_path, monkeypatch, "binance")
    def changed(payload):
        payload["raw"]["account"]["availableBalance"] = "0"
        for row in payload["raw"]["account"]["assets"]:
            row["availableBalance"] = "0"
    account = snapshot_copy(inputs["after"], changed)
    payload = quantity_api()(db, key, phase="close", account_snapshot=account, pending_orders=params["pending_orders"])["payload"]
    assert payload["observed_available_base_quantity"] == "0.02"
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False


@pytest.mark.parametrize("name", ["_number", "_market", "_string", "account_key", "_sha"])
def test_actual_quantity_aliases_are_pinned_not_only_the_original_defining_module(store, monkeypatch, name):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    delegate = getattr(Management, name)
    monkeypatch.setattr(Management, name, lambda *a, **k: delegate(*a, **k))
    with pytest.raises(CChanException):
        Management._source_runtime(engine)


def test_management_runtime_cannot_switch_the_saved_role_mode_before_collection(store):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    engine.mode = "testnet"
    with pytest.raises(CChanException):
        Management._source_runtime(engine)
