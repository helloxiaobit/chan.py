"""Original intents plus independent native pending rows; no exchange I/O."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.db_util import CChanDB
from .test_crypto_venue_parameters import venue_engine
from .test_execution_store import store
from .test_m6_trade import make_signal
from .test_native_admission_interval import explicit_path_environment
from .test_native_pending_orders import NOW, pending_source, pending_api, regular_row, algo_row


def ownership_api():
    assert importlib.util.find_spec("Trade.NativePendingOwnership") is not None, "original-ledger pending ownership is missing"
    from Trade.NativePendingOwnership import observe_native_pending_ownership
    return observe_native_pending_ownership


def case(db, tmp_path, monkeypatch, source, *, mode="one_way", side=True, closing=False, same_server_ids=False):
    clock = [NOW-10000]
    for module in ("Trade.OrderAudit", "Trade.db_util", "tests.test_crypto_order_contract"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock[0])
    trade = venue_engine(db, tmp_path, source.venue, mode)
    if same_server_ids:
        create = trade.exchange.create_order
        def create_per_market(*args, **kwargs):
            row = create(*args, **kwargs)
            row["id"] = "77"
            return row
        monkeypatch.setattr(trade.exchange, "create_order", create_per_market)
    if source.venue == "binance":
        trade.exchange.account_alias = "fake-Futures-A"
    first = trade.exchange.market("TEST/USDT:USDT")
    second = copy.deepcopy(first)
    second.update(symbol="ALT/USDT:USDT", base="ALT", baseId="ALT", contractSize=0.1,
                  id="ALTUSDT" if source.venue == "binance" else "ALT-USDT-SWAP")
    trade.exchange.set_markets([first, second])
    trade.exchange.builder.set_markets([first, second])
    source.markets[:] = [trade._market_contract(row["symbol"])[0] for row in (first, second)]
    for rows in source.rows.values():
        rows.clear()
    keys = []
    for market in source.markets:
        trade.quota_gen = CBenchPriceQuotaGen(float(Decimal(market["contractSize"])*3*100+Decimal("0.7")))
        trade.exchange.fill, trade.exchange.status = (3, "closed") if closing else (1, "open")
        key = db.add_signal(make_signal(code=market["symbol"], is_buy=side))
        trade.add_trade(db.get_record(key), 100)
        clock[0] += 100
        if closing:
            trade.exchange.fill, trade.exchange.status = 1, "open"
            trade.cover_trade(db.get_record(key), 101, "pending close")
        record = db.get_record(key)
        prefix = "cover" if closing else "open"
        contract = json.loads(record[prefix+"_order_contract"])
        native = regular_row(source.venue, market["id"], int(record[prefix+"_order_id"]), partial=True)
        client, leg = record[prefix+"_client_order_id"], record["position_side"]
        if source.venue == "binance":
            native.update(origQty=contract["quantity"], executedQty=str(Decimal(market["contractSize"])),
                          clientOrderId=client, side="BUY" if side != closing else "SELL", positionSide=leg,
                          price=contract["price"], reduceOnly=closing and mode == "one_way",
                          time=clock[0], updateTime=clock[0]+1)
        else:
            native.update(sz=contract["exchange_amount"], accFillSz="1", clOrdId=client,
                          side="buy" if side != closing else "sell", posSide="net" if leg == "BOTH" else leg.lower(),
                          px=contract["price"], reduceOnly="true" if closing and mode == "one_way" else "false",
                          cTime=str(clock[0]), uTime=str(clock[0]+1))
        source.rows["regular"].append(native)
        keys.append(key)
        clock[0] += 100
    document = pending_api(source).collect_native_pending_orders(source.client, source.markets, mode=source.mode)
    return trade, keys, document


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("mode,side,closing", [(mode, side, closing) for mode in ("one_way", "hedged")
                                             for side in (True, False) for closing in (False, True)])
def test_nonempty_pending_binds_original_open_or_close_attempts_without_releasing_reservations(
        store, tmp_path, monkeypatch, pending_source, mode, side, closing):
    read = ownership_api()  # Genuine missing behavior RED before fixture work.
    db, conf = store
    trade, keys, document = case(db, tmp_path, monkeypatch, pending_source, mode=mode, side=side, closing=closing)
    original = [db.get_record(key) for key in keys]
    histories = [db.get_order_history(key) for key in keys]
    changes, calls = db.db.conn.total_changes, len(pending_source.calls)
    report = read(db, pending_orders=document)
    payload = report["payload"]
    assert report["schema"] == "chan-native-pending-ownership-v1"
    assert payload["issues"] == [] and len(payload["orders"]) == len(payload["reservations"]) == 2
    assert all(row["status"] == "owned" and row["reason"] is None for row in payload["orders"])
    assert {row["attempt"]["phase"] for row in payload["orders"]} == {"close" if closing else "open"}
    assert {row["remaining_base_quantity"] for row in payload["reservations"]} == {"0.02", "0.2"}
    assert {row["remaining_contracts"] for row in payload["reservations"]} == {"2"}
    assert all(row["native_pending_matched"] is True and row["native_margin_amount"] is None for row in payload["reservations"])
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    assert payload["source_pending_sha256"] == document["payload_sha256"]
    assert db.db.conn.total_changes == changes and len(pending_source.calls) == calls
    assert [db.get_record(key) for key in keys] == original
    assert [db.get_order_history(key) for key in keys] == histories
    assert len(trade.exchange.created) == (4 if closing else 2)
    reopened = CChanDB(db_conf=conf)
    try:
        assert read(reopened, pending_orders=document) == report
    finally:
        reopened.close()


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_empty_native_lists_do_not_release_local_unfilled_requests(store, tmp_path, monkeypatch, pending_source):
    read = ownership_api()
    db, _ = store
    _, keys, _ = case(db, tmp_path, monkeypatch, pending_source)
    pending_source.rows["regular"].clear()
    source = pending_api(pending_source).collect_native_pending_orders(pending_source.client, pending_source.markets, mode=pending_source.mode)
    report = read(db, pending_orders=source)["payload"]
    assert report["orders"] == [] and len(report["reservations"]) == 2
    assert all(row["native_pending_matched"] is False for row in report["reservations"])
    assert {row["remaining_base_quantity"] for row in report["reservations"]} == {"0.02", "0.2"}
    assert {issue["reason"] for issue in report["issues"]} == {"local_pending_not_observed"}
    assert [db.get_record(key)["open_order_status"] for key in keys] == ["open", "open"]


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage,reason", [("client", "client_id_mismatch"), ("quantity", "pending_quantity_difference"),
    ("filled", "pending_quantity_difference"), ("price", "order_terms_mismatch"), ("time_in_force", "order_terms_mismatch"),
    ("side", "side_mismatch"), ("leg", "position_side_mismatch"), ("reduce_only", "reduce_only_mismatch")])
def test_independently_observed_pending_mismatch_never_rewrites_the_original_attempt(
        store, tmp_path, monkeypatch, pending_source, damage, reason):
    read = ownership_api()
    db, _ = store
    _, keys, _ = case(db, tmp_path, monkeypatch, pending_source)
    s = pending_source
    row = s.rows["regular"][0]
    if damage == "client":
        row["clientOrderId" if s.venue == "binance" else "clOrdId"] = "cpNotThisOwner"
    elif damage == "quantity":
        row["origQty" if s.venue == "binance" else "sz"] = "0.04" if s.venue == "binance" else "4"
    elif damage == "filled":
        row["executedQty" if s.venue == "binance" else "accFillSz"] = "0.02" if s.venue == "binance" else "2"
    elif damage == "price":
        row["price" if s.venue == "binance" else "px"] = "105"
    elif damage == "time_in_force":
        row["timeInForce" if s.venue == "binance" else "ordType"] = "IOC" if s.venue == "binance" else "ioc"
    elif damage == "side":
        row["side"] = "SELL" if s.venue == "binance" else "sell"
    elif damage == "leg":
        row["positionSide" if s.venue == "binance" else "posSide"] = "LONG" if s.venue == "binance" else "long"
    else:
        row["reduceOnly"] = True if s.venue == "binance" else "true"
    document = pending_api(s).collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    original, changes = db.get_record(keys[0]), db.db.conn.total_changes
    report = read(db, pending_orders=document)["payload"]
    rejected = [row for row in report["orders"] if row["status"] == "unowned"]
    assert len(rejected) == 1 and rejected[0]["reason"] == reason
    assert sum(row["native_pending_matched"] for row in report["reservations"]) == 1
    assert db.get_record(keys[0]) == original and db.db.conn.total_changes == changes


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("claimed", [False, True])
def test_created_or_claimed_intent_in_another_table_remains_reserved_with_no_assumed_absence(
        store, tmp_path, monkeypatch, pending_source, claimed):
    read = ownership_api()
    db, conf = store
    trade, _, document = case(db, tmp_path, monkeypatch, pending_source)
    other = CChanDB(db_conf=conf, table_name="other_trades")
    try:
        key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        qty, _, contract = trade.prepare_order("TEST/USDT:USDT", 0.03, 100, record=other.get_record(key))
        assert other.acquire_open_intent(key, qty, "cpOtherPending", order_contract=contract)
        if claimed:
            assert other.claim_order_submission(key, "open")
        before = other.get_record(key)
        report = read(db, pending_orders=document)["payload"]
        extra = [row for row in report["reservations"] if row["attempt"]["trade_table"] == "other_trades"]
        assert len(extra) == 1 and extra[0]["remaining_base_quantity"] == "0.03"
        assert extra[0]["remaining_contracts"] == "3" and extra[0]["native_pending_matched"] is False
        assert extra[0]["local_order_status"] == ("submitting" if claimed else "created")
        assert {row["reason"] for row in report["issues"]} == {"local_pending_not_observed"}
        assert other.get_record(key) == before and before["open_order_id"] is None
    finally:
        other.close()


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_mutable_projection_cannot_overwrite_original_pending_fill_history(store, tmp_path, monkeypatch, pending_source):
    read = ownership_api()
    db, _ = store
    _, keys, document = case(db, tmp_path, monkeypatch, pending_source)
    db.db.execute("UPDATE chan_trade SET open_filled_qty=0 WHERE id=?", (keys[0],))
    with pytest.raises(CChanException):
        read(db, pending_orders=document)


def original_intent(db, trade, *, client="cpAnotherIntent", damage=None, server_id=None, price=100, post_only=False):
    """Use original CAS/events; invalid contracts are new inputs, never resealed history."""
    key = db.add_signal(make_signal(code="TEST/USDT:USDT"))
    qty, _, contract = trade.prepare_order("TEST/USDT:USDT", 0.03, price, record=db.get_record(key), post_only=post_only)
    if damage is not None:
        damage(contract)
        contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    assert db.acquire_open_intent(key, qty, client, order_contract=contract)
    assert db.claim_order_submission(key, "open")
    if server_id is not None:
        db.record_order_ack(key, "open", server_id, client_order_id=client, expected_attempt=1)
        db.apply_open_fill(key, 0.01, 100, order_status="open", order_id=server_id, client_order_id=client, expected_attempt=1)
    return key


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("ack", [False, True])
def test_native_presence_cannot_repair_missing_ack_or_submitting_state(store, tmp_path, monkeypatch, pending_source, ack):
    read = ownership_api()
    db, _ = store
    trade, _, _ = case(db, tmp_path, monkeypatch, pending_source)
    key = original_intent(db, trade)
    if ack:
        db.record_order_ack(key, "open", "999", client_order_id="cpAnotherIntent", expected_attempt=1)
    native = regular_row(pending_source.venue, pending_source.markets[0]["id"], 999)
    native.update({"clientOrderId": "cpAnotherIntent", "origQty": "0.03", "time": NOW-1000, "updateTime": NOW-999}
                  if pending_source.venue == "binance" else
                  {"clOrdId": "cpAnotherIntent", "sz": "3", "cTime": str(NOW-1000), "uTime": str(NOW-999)})
    pending_source.rows["regular"].append(native)
    source = pending_api(pending_source).collect_native_pending_orders(pending_source.client, pending_source.markets, mode=pending_source.mode)
    before, history, changes = db.get_record(key), db.get_order_history(key), db.db.conn.total_changes
    report = read(db, pending_orders=source)["payload"]
    row = next(row for row in report["orders"] if row["native_order"][2] == "999")
    assert row["status"] == "unowned" and row["reason"] == ("local_order_state_unresolved" if ack else "unrecorded_order")
    reservation = next(row for row in report["reservations"] if row["attempt"]["record_id"] == key)
    assert reservation["remaining_base_quantity"] == "0.03" and not reservation["native_pending_matched"]
    assert db.get_record(key) == before and db.get_order_history(key) == history and db.db.conn.total_changes == changes
    assert not db.claim_order_submission(key, "open")


@pytest.mark.parametrize("pending_source", [("binance", "testnet")], indirect=True)
def test_binance_same_native_id_in_different_markets_has_distinct_original_owners(store, tmp_path, monkeypatch, pending_source):
    db, _ = store
    _, keys, source = case(db, tmp_path, monkeypatch, pending_source, same_server_ids=True)
    assert [db.get_record(key)["open_order_id"] for key in keys] == ["77", "77"]
    report = ownership_api()(db, pending_orders=source)["payload"]
    assert report["issues"] == []
    assert {row["attempt"]["record_id"] for row in report["orders"]} == set(keys)


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("foreign", [False, True])
def test_same_market_server_id_collision_requires_unique_stable_account_owner(store, tmp_path, monkeypatch, pending_source, foreign):
    db, conf = store
    trade, keys, source = case(db, tmp_path, monkeypatch, pending_source)
    if foreign:
        if pending_source.venue == "binance":
            trade.exchange.account_alias = "fake-Futures-B"
        else:
            trade.exchange.account_uid = "87654321"
    other = CChanDB(db_conf=conf, table_name="colliding_trades")
    try:
        original_intent(other, trade, server_id=db.get_record(keys[0])["open_order_id"])
        report = ownership_api()(db, pending_orders=source)["payload"]
        target = next(row for row in report["orders"] if row["native_order"][1] == pending_source.markets[0]["id"])
        assert target["status"] == ("owned" if foreign else "unowned")
        assert target["reason"] == (None if foreign else "ambiguous_order_id")
        if foreign:
            assert report["issues"] == [] and len(report["reservations"]) == 2
        else:
            assert len(report["reservations"]) == 3 and sum(row["native_pending_matched"] for row in report["reservations"]) == 1
    finally:
        other.close()


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_terminal_local_attempt_cannot_own_a_still_pending_native_order(store, tmp_path, monkeypatch, pending_source):
    db, _ = store
    _, keys, source = case(db, tmp_path, monkeypatch, pending_source)
    stored = db.get_record(keys[0])
    db.apply_open_fill(keys[0], 0.01, 100, order_status="canceled", order_id=stored["open_order_id"],
                       client_order_id=stored["open_client_order_id"], expected_attempt=stored["open_attempt"])
    report = ownership_api()(db, pending_orders=source)["payload"]
    target = next(row for row in report["orders"] if row["native_order"][1] == pending_source.markets[0]["id"])
    assert target["status"] == "unowned" and target["reason"] == "local_order_state_unresolved"
    assert len(report["reservations"]) == 1 and report["native_admission_verified"] is False


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("kind,reason", [("algo", "native_algo_ownership_unproven"),
    ("complex", "complex_native_order_terms"), ("foreign_market", "unmapped_native_market")])
def test_unmanaged_native_terms_remain_unowned_even_with_recorded_server_id(store, tmp_path, monkeypatch, pending_source, kind, reason):
    db, _ = store
    _, keys, _ = case(db, tmp_path, monkeypatch, pending_source)
    row = pending_source.rows["regular"][0]
    if kind == "algo":
        pending_source.rows["regular"].remove(row)
        pending_source.rows["conditional"].append(algo_row(pending_source.venue, pending_source.markets[0]["id"], int(db.get_record(keys[0])["open_order_id"])))
    elif kind == "complex":
        row.update({"priceMatch": "OPPONENT"} if pending_source.venue == "binance" else {"tpTriggerPx": "110"})
    else:
        row["symbol" if pending_source.venue == "binance" else "instId"] = "FOREIGNUSDT" if pending_source.venue == "binance" else "FOREIGN-USDT-SWAP"
    source = pending_api(pending_source).collect_native_pending_orders(pending_source.client, pending_source.markets, mode=pending_source.mode)
    report = ownership_api()(db, pending_orders=source)["payload"]
    unowned = [row for row in report["orders"] if row["status"] == "unowned"]
    assert len(unowned) == 1 and unowned[0]["reason"] == reason
    assert sum(row["native_pending_matched"] for row in report["reservations"]) == 1


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage", ["quantity_unit", "exchange_unit", "exchange_quantity", "notional", "leverage", "mode", "observation", "post_only"])
def test_invalid_original_execution_contract_cannot_become_a_quantity_reservation(store, tmp_path, monkeypatch, pending_source, damage):
    db, _ = store
    trade, _, source = case(db, tmp_path, monkeypatch, pending_source)
    def alter(contract):
        if damage == "quantity_unit":
            contract["quantity_unit"] = "contracts"
        elif damage == "exchange_unit":
            contract["exchange_amount_unit"] = "base_currency"
        elif damage == "exchange_quantity":
            contract["exchange_amount"] = "4"
        elif damage == "notional":
            contract["notional"] = "30"
        elif damage == "leverage":
            contract["execution"]["leverage"] = 0
        elif damage == "mode":
            contract["execution"]["position_mode"] = "hedged"
        elif damage == "observation":
            contract["account_observation"]["margin_mode"] = "isolated"
        else:
            contract["post_only"] = 1
    original_intent(db, trade, damage=alter)
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException):
        ownership_api()(db, pending_orders=source)
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_actual_accepted_response_loss_keeps_the_original_claim_and_native_order_separate(store, tmp_path, monkeypatch, pending_source):
    from .test_crypto_order_recovery import recovery_engine, lose_open
    db, _ = store
    _, _, _ = case(db, tmp_path, monkeypatch, pending_source)
    monkeypatch.setattr("tests.test_crypto_order_recovery.utc_now_ms", lambda: NOW-8000)
    trade = recovery_engine(db, tmp_path, pending_source.venue)
    trade.exchange.account_alias = "fake-Futures-A"
    key = lose_open(trade)  # Actual fake HTTP acceptance, followed by RequestTimeout.
    record = db.get_record(key)
    native = regular_row(pending_source.venue, pending_source.markets[0]["id"], 999)
    native.update({"clientOrderId": record["open_client_order_id"], "origQty": "0.03", "time": NOW-8000, "updateTime": NOW-7999}
                  if pending_source.venue == "binance" else
                  {"clOrdId": record["open_client_order_id"], "sz": "3", "cTime": str(NOW-8000), "uTime": str(NOW-7999)})
    pending_source.rows["regular"].append(native)
    source = pending_api(pending_source).collect_native_pending_orders(pending_source.client, pending_source.markets, mode=pending_source.mode)
    history, changes = db.get_order_history(key), db.db.conn.total_changes
    report = ownership_api()(db, pending_orders=source)["payload"]
    assert trade.exchange.orders and len(trade.exchange.created) == 1
    assert record["open_order_id"] is None and record["open_order_status"] == "submitting"
    assert any(row["reason"] == "unrecorded_order" for row in report["orders"])
    reservation = next(row for row in report["reservations"] if row["attempt"]["record_id"] == key)
    assert reservation["remaining_base_quantity"] == "0.03" and not reservation["native_pending_matched"]
    assert db.get_record(key) == record and db.get_order_history(key) == history and db.db.conn.total_changes == changes
    assert not db.claim_order_submission(key, "open") and len(trade.exchange.created) == 1


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("problem", ["missing_contract", "missing_history", "environment"])
def test_unidentified_or_incomplete_history_is_not_silently_excluded(store, tmp_path, monkeypatch, pending_source, problem):
    db, conf = store
    trade, _, source = case(db, tmp_path, monkeypatch, pending_source)
    other = CChanDB(db_conf=conf, table_name="unidentified_trades")
    try:
        if problem == "environment":
            def alter(contract):
                context = contract["account_context"]
                routes = context["environment"]["private_routes"]
                routes[next(iter(routes))] = "https://historical.invalid/private"
                context["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in context.items() if k != "context_id"})).hexdigest()
            original_intent(other, trade, damage=alter)
            expected = "historical_account_environment_drift"
        else:
            key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
            if problem == "missing_contract":
                assert other.acquire_open_intent(key, 0.03, "cpNoUnitContract")
                expected = "unidentified_attempt"
            else:
                # An old nonzero position without any identified attempt.
                other.db.execute("UPDATE unidentified_trades SET current_qty=0.03,open_filled_qty=0.03 WHERE id=?", (key,))
                expected = "incomplete_attempt_history"
        changes = db.db.conn.total_changes
        report = ownership_api()(db, pending_orders=source)["payload"]
        assert expected in {row["reason"] for row in report["issues"]}
        assert report["native_admission_verified"] is False and db.db.conn.total_changes == changes
    finally:
        other.close()


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("change_input", [False, True])
def test_db_read_owns_a_savepoint_and_rejects_a_changing_source_packet(store, tmp_path, monkeypatch, pending_source, change_input):
    db, _ = store
    _, keys, source = case(db, tmp_path, monkeypatch, pending_source)
    read, query = ownership_api(), db.db.query
    def inspect(sql, *args, **kwargs):
        assert db.db.conn.in_transaction
        if change_input:
            source["payload"]["economics_complete"] = True
        return query(sql, *args, **kwargs)
    monkeypatch.setattr(db.db, "query", inspect)
    with db.db.transaction():
        changes = db.db.conn.total_changes
        if change_input:
            with pytest.raises(CChanException):
                read(db, pending_orders=source)
        else:
            assert len(read(db, pending_orders=source)["payload"]["reservations"]) == 2
        assert db.db.conn.in_transaction and db.db.conn.total_changes == changes
    assert not db.db.conn.in_transaction
    monkeypatch.setattr(db.db, "query", query)
    assert [db.get_record(key)["open_order_status"] for key in keys] == ["open", "open"]


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_original_ledger_and_source_reader_need_no_optional_sdk_or_actual_configuration(store, tmp_path, monkeypatch, pending_source):
    db, conf = store
    _, _, source = case(db, tmp_path, monkeypatch, pending_source)
    expected = ownership_api()(db, pending_orders=source)
    code = """
import importlib.abc, json, sys
blocked = {'ccxt', 'xgboost', 'lightgbm', 'sklearn', 'optuna', 'yaml', 'PyQt6', 'minio', 'qcloud_cos'}
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            attempted.append(fullname)
            raise ModuleNotFoundError('optional dependency intentionally absent')
sys.meta_path.insert(0, BlockOptional())
from Config.EnvConfig import CEnv
from Trade.db_util import CChanDB
from Trade.NativePendingOwnership import observe_native_pending_ownership
import Trade.NativePendingOrders as native_pending
from CustomBuySellPoint.Decision import canonical_bytes
values = json.loads(sys.stdin.buffer.read())
native_pending.utc_now_ms = lambda: values['now']
env = CEnv.__new__(CEnv)
env.conf = {}
CEnv._instance = env
db = CChanDB(db_conf=values['db'])
try:
    before = db.db.conn.total_changes
    assert observe_native_pending_ownership(db, pending_orders=values['source']) == values['expected']
    assert db.db.conn.total_changes == before and not db.db.conn.in_transaction
finally:
    db.close()
assert not attempted, attempted
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('Original pending ownership without optional SDK PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes({"db": conf, "source": source, "expected": expected,
                                                                            "now": pending_source.clock["now"]}),
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"Original pending ownership without optional SDK PASS" and result.stderr == b""


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("event_ms", [NOW-20000, NOW+1000])
def test_regressed_or_post_observation_local_events_cannot_reuse_a_pending_snapshot(store, tmp_path, monkeypatch, pending_source, event_ms):
    db, _ = store
    _, keys, source = case(db, tmp_path, monkeypatch, pending_source)
    stored = db.get_record(keys[0])
    monkeypatch.setattr("Trade.OrderAudit.utc_now_ms", lambda: event_ms)
    db.apply_open_fill(keys[0], 0.02, 101, order_status="open", order_id=stored["open_order_id"],
                       client_order_id=stored["open_client_order_id"], expected_attempt=stored["open_attempt"])
    pending_source.rows["regular"][0]["executedQty" if pending_source.venue == "binance" else "accFillSz"] = "0.02" if pending_source.venue == "binance" else "2"
    source = pending_api(pending_source).collect_native_pending_orders(pending_source.client, pending_source.markets, mode=pending_source.mode)
    with pytest.raises(CChanException):
        ownership_api()(db, pending_orders=source)


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("price,post_only", [(None, False), (100, True)])
def test_original_market_and_maker_intents_keep_their_distinct_native_terms(store, tmp_path, monkeypatch, pending_source, price, post_only):
    db, _ = store
    trade, _, _ = case(db, tmp_path, monkeypatch, pending_source)
    key = original_intent(db, trade, server_id="999", price=price, post_only=post_only)
    source = pending_source
    row = copy.deepcopy(source.rows["regular"][0])
    if source.venue == "binance":
        row.update(orderId=999, clientOrderId="cpAnotherIntent", type="LIMIT" if post_only else "MARKET",
                   origType="LIMIT" if post_only else "MARKET", price="100" if post_only else "0", timeInForce="GTX" if post_only else "GTC",
                   time=NOW-1000, updateTime=NOW-999)
    else:
        row.update(ordId="999", clOrdId="cpAnotherIntent", ordType="post_only" if post_only else "market", px="100" if post_only else "",
                   cTime=str(NOW-1000), uTime=str(NOW-999))
    source.rows["regular"].append(row)
    document = pending_api(source).collect_native_pending_orders(source.client, source.markets, mode=source.mode)
    report = ownership_api()(db, pending_orders=document)["payload"]
    assert report["issues"] == []
    matched = next(row for row in report["orders"] if row["native_order"][2] == "999")
    assert matched["status"] == "owned" and matched["attempt"]["record_id"] == key
