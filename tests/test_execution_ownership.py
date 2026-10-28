"""Real multi-attempt history, independently normalized native facts, no HTTP."""
import copy
import hashlib
from decimal import Decimal, Subnormal, localcontext

import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.ExecutionReconcile import build_execution_ownership
from Trade.db_util import CChanDB
from . import test_crypto_order_contract as order_fixture
from .test_crypto_order_contract import CODE
from .test_crypto_venue_parameters import venue_engine
from .test_execution_account_binding import observation
from .test_execution_facts import NativeSources, collect, fill, funding
from .test_execution_store import store
from .test_m6_trade import make_signal


def scenario(db, tmp_path, monkeypatch, venue, *, side=True, mode="one_way", other_account=False):
    import Trade.db_util as db_module
    clock = [utc_now_ms()-5_000]
    monkeypatch.setattr(db_module, "utc_now_ms", lambda: clock[0])
    monkeypatch.setattr(order_fixture, "utc_now_ms", lambda: clock[0])
    trade = venue_engine(db, tmp_path, venue, mode)
    if other_account:
        from .test_crypto_account_binding import switch_account
        switch_account(trade.exchange)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = db.add_signal(make_signal(code=CODE, is_buy=side))
    order_fixture.open_legacy_history(trade, db.get_record(key), 100)
    clock[0] += 100
    trade.exchange.fill, trade.exchange.status = 1, "canceled"
    trade.cover_trade(db.get_record(key), 101, "first partial close")
    clock[0] += 100
    trade.exchange.fill, trade.exchange.status = 2, "closed"
    trade.cover_trade(db.get_record(key), 102, "finish close")
    history = db.get_order_history(key)
    rows = []
    for i, order in enumerate(trade.exchange.orders.values(), 1):
        quantity = str(Decimal(str(order["filled"]))*Decimal("0.01")) if venue == "binance" else str(order["filled"])
        row = fill(venue, order["timestamp"], key=100+i, price=str(order["average"]),
            quantity=quantity, side=order["side"], leg=db.get_record(key)["position_side"])
        row["orderId" if venue == "binance" else "ordId"] = order["id"]
        if venue == "okx":
            row["clOrdId"] = order["clientOrderId"]
        rows.append(row)
    return trade, key, history, rows, clock[0]-300, clock[0]+100


def source_scan(venue, rows, start, end, *, cash=True):
    return collect(NativeSources(venue, rows, [funding(venue, end-1)] if cash else []), start, end)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("side,mode", [(True, "one_way"), (False, "one_way"), (True, "hedged"), (False, "hedged")])
def test_every_native_trade_uses_its_historical_attempt_not_the_current_close_slot(store, tmp_path, monkeypatch, venue, side, mode):
    db, conf = store
    trade, key, history, rows, start, end = scenario(db, tmp_path, monkeypatch, venue, side=side, mode=mode)
    receipt, observed = source_scan(venue, rows, start, end), observation(trade)
    before = db.get_record(key)
    db.store_execution_scan(receipt, account_observation=observed)
    report = db.get_execution_ownership(receipt["payload_sha256"])
    payload = report["payload"]
    assert report == build_execution_ownership(receipt, observed["before"], [history])
    assert payload["coverage"] == "observed_scan_facts_only" and payload["economics_complete"] is False
    assert [(t["status"], t["attempt"]["phase"], t["attempt"]["attempt"], t["attempt"]["order_id"]) for t in payload["trades"]] == [
        ("owned", "open", 1, "1"), ("owned", "close", 1, "2"), ("owned", "close", 2, "3")]
    assert [t["quantity"] for t in payload["trades"]] == ["0.03", "0.01", "0.02"]
    assert payload["funding"] == [{"source_id": "901", "status": "unallocated", "reason": "native_leg_missing"}]
    assert payload["history_sha256"] == hashlib.sha256(canonical_bytes([history])).hexdigest()
    assert db.get_record(key) == before and db.get_order_history(key) == history
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_execution_ownership(receipt["payload_sha256"]) == report
    finally:
        reopened.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage,reason", [
    ("foreign_order", "unrecorded_order"), ("side", "side_mismatch"), ("leg", "position_side_mismatch"),
    ("time", "before_intent"), ("overfill", "requested_quantity_exceeded"),
    ("account", "account_context_mismatch"), ("units", "market_mismatch"),
    ("legacy", "legacy_attempt"), ("ambiguous", "ambiguous_order_id"),
])
def test_single_ownership_mutation_has_explicit_unowned_record_not_a_best_match(store, tmp_path, monkeypatch, venue, damage, reason):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, venue)
    histories = [copy.deepcopy(history)]
    first = rows[0]
    if damage == "foreign_order":
        first["orderId" if venue == "binance" else "ordId"] = "999"
    elif damage == "side":
        first["side"] = "SELL" if venue == "binance" else "sell"
        if venue == "binance":
            first["buyer"] = False
    elif damage == "leg":
        first["positionSide" if venue == "binance" else "posSide"] = "SHORT" if venue == "binance" else "short"
    elif damage == "time":
        first["time" if venue == "binance" else "fillTime"] = history["attempts"][0]["identity"]["intent_ms"]-1
    elif damage == "overfill":
        first["qty" if venue == "binance" else "fillSz"] = "0.04" if venue == "binance" else "4"
    elif damage == "account":
        histories[0]["attempts"][0]["identity"]["order_contract"]["account_context"] = observation(venue_engine(db, tmp_path, "okx" if venue == "binance" else "binance"))["before"]
    elif damage == "units":
        histories[0]["attempts"][0]["identity"]["order_contract"]["market"]["contractSize"] = "0.1"
    elif damage == "legacy":
        histories[0]["attempts"][0]["origin"] = "legacy_snapshot"
    else:
        duplicate = copy.deepcopy(histories[0]["attempts"][0])
        duplicate["identity"]["record_id"] += 100
        histories[0]["attempts"].append(duplicate)
    if damage in {"account", "units"}:
        # Model a different frozen attempt, not just a broken hash. Hash damage
        # is tested separately and must never authorize ownership either.
        identity = histories[0]["attempts"][0]["identity"]
        contract = identity["order_contract"]
        contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
        identity["contract_sha256"] = hashlib.sha256(canonical_bytes(contract)).hexdigest()
    report = build_execution_ownership(source_scan(venue, rows, start, end), observation(trade)["before"], histories)
    record = next(t for t in report["payload"]["trades"] if t["source_id"] == ("101" if venue == "binance" else "1101"))
    assert record["status"] == "unowned" and record["reason"] == reason and record["attempt"] is None
    assert len([r for r in report["payload"]["trades"] if r["status"] == "owned"]) == 2
    assert report["payload"]["economics_complete"] is False


def test_okx_missing_fill_clock_or_client_conflict_is_not_silently_owned(store, tmp_path, monkeypatch):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, "okx")
    del rows[0]["fillTime"]
    rows[1]["clOrdId"] = "otherclient"
    report = build_execution_ownership(source_scan("okx", rows, start, end), observation(trade)["before"], [history])
    assert [t["reason"] for t in report["payload"]["trades"]] == ["missing_fill_time", "client_id_mismatch", None]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_combined_native_fills_cannot_exceed_one_frozen_request(store, tmp_path, monkeypatch, venue):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, venue)
    rows = [copy.deepcopy(rows[0]), copy.deepcopy(rows[0])]
    for row in rows:
        row["qty" if venue == "binance" else "fillSz"] = "0.02" if venue == "binance" else "2"
    rows[1]["id" if venue == "binance" else "billId"] = 1009
    report = build_execution_ownership(source_scan(venue, rows, start, end), observation(trade)["before"], [history])
    assert [t["reason"] for t in report["payload"]["trades"]] == ["requested_quantity_exceeded"]*2


def test_db_ownership_reader_rejects_unbound_scan_and_corrupt_history(store, tmp_path, monkeypatch):
    db, _ = store
    trade, key, _, rows, start, end = scenario(db, tmp_path, monkeypatch, "binance")
    receipt = source_scan("binance", rows, start, end)
    db.store_execution_scan(receipt)
    with pytest.raises(CChanException):
        db.get_execution_ownership(receipt["payload_sha256"])
    receipt = source_scan("binance", rows, start, end, cash=False)
    db.store_execution_scan(receipt, account_observation=observation(trade))
    db.db.execute("UPDATE chan_trade SET current_qty=99 WHERE id=?", (key,))
    with pytest.raises(CChanException):
        db.get_execution_ownership(receipt["payload_sha256"])


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_native_server_id_collision_in_another_account_is_not_the_same_attempt(store, tmp_path, monkeypatch, venue):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, venue)
    other = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"other-account.db")})
    try:
        _, _, second, _, _, _ = scenario(other, tmp_path, monkeypatch, venue, other_account=True)
        source = source_scan(venue, rows, start, end)
        report = build_execution_ownership(source, observation(trade)["before"], [second, history])
        assert all(t["status"] == "owned" for t in report["payload"]["trades"])
        assert report["payload"]["economics_complete"] is False
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_missing_ack_is_not_inferred_from_native_fills_but_verified_restore_can_supply_it(store, tmp_path, monkeypatch, venue):
    import Trade.db_util as db_module
    from . import test_crypto_order_recovery as recovery_fixture
    db, _ = store
    at = utc_now_ms()-5_000
    monkeypatch.setattr(db_module, "utc_now_ms", lambda: at)
    monkeypatch.setattr(order_fixture, "utc_now_ms", lambda: at)
    monkeypatch.setattr(recovery_fixture, "utc_now_ms", lambda: at)
    trade = recovery_fixture.recovery_engine(db, tmp_path, venue)
    key = recovery_fixture.lose_open(trade)
    record = db.get_record(key)
    row = fill(venue, at+1, quantity="0.01" if venue == "binance" else "1")
    row["orderId" if venue == "binance" else "ordId"] = "1"
    if venue == "okx":
        row["clOrdId"] = record["open_client_order_id"]
    source = source_scan(venue, [row], at-1, at+1000)
    db.store_execution_scan(source, account_observation=observation(trade))
    before = db.get_execution_ownership(source["payload_sha256"])
    assert before["payload"]["trades"][0]["reason"] == "unrecorded_order"
    assert db.get_record(key)["open_order_id"] is None
    trade.restore()
    after = db.get_execution_ownership(source["payload_sha256"])
    assert after["payload"]["trades"][0]["status"] == "owned"
    assert before["payload"]["history_sha256"] != after["payload"]["history_sha256"]
    assert len(trade.exchange.created) == 1


def test_empty_bound_scan_never_becomes_an_account_pass(store, tmp_path):
    db, _ = store
    trade = venue_engine(db, tmp_path, "binance")
    start = utc_now_ms()-5_000
    source = source_scan("binance", [], start, start+100, cash=False)
    db.store_execution_scan(source, account_observation=observation(trade))
    payload = db.get_execution_ownership(source["payload_sha256"])["payload"]
    assert payload["trades"] == payload["funding"] == []
    assert payload["economics_complete"] is False and payload["coverage"] == "observed_scan_facts_only"


@pytest.mark.parametrize("damage", ["contract_id", "contract_sha256"])
def test_malformed_frozen_contract_fingerprint_cannot_authorize_ownership(store, tmp_path, monkeypatch, damage):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, "binance")
    identity = history["attempts"][0]["identity"]
    target = identity["order_contract"] if damage == "contract_id" else identity
    target[damage] = "0"*64
    report = build_execution_ownership(source_scan("binance", rows, start, end), observation(trade)["before"], [history])
    assert report["payload"]["trades"][0]["status"] == "unowned"
    assert report["payload"]["trades"][0]["reason"] == "invalid_contract"


def test_ownership_quantity_arithmetic_does_not_inherit_callers_decimal_traps(store, tmp_path, monkeypatch):
    db, _ = store
    trade, _, history, rows, start, end = scenario(db, tmp_path, monkeypatch, "binance")
    source, account = source_scan("binance", rows, start, end), observation(trade)["before"]
    expected = build_execution_ownership(source, account, [history])
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 2, 1, -1
        context.traps[Subnormal] = True
        assert build_execution_ownership(source, account, [history]) == expected
