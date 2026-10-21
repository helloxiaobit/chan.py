"""Full paper runs through the actual SQLite intent/CAS/recovery engine."""
from decimal import Decimal
import hashlib

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.CCXTTradeEngine import CCCXTTradeEngine, CSimExchangeState
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from .test_crypto_order_contract import CODE
from .test_execution_store import store
from .test_linear_paper_account import paper_account
from .test_m6_trade import make_signal


def paper_engine(db, *, state=None, account=None):
    state = state or CSimExchangeState(paper_account=account or paper_account(mode="one_way"))
    result = CCCXTTradeEngine(db, sim_state=state, quota_gen=CBenchPriceQuotaGen(3.7),
        ccxt_conf={"mode": "dry_run", "default_type": "swap"}, trade_conf={}, environ={}, push_msg=False)
    result.api_interval = 0
    return result


def quote(engine, at, *, bid="99.9", ask="100", mark="100"):
    engine.set_sim_quote(CODE, at_ms=at, bid=bid, ask=ask, mark_price=mark)


def test_software_units_actual_adverse_price_and_cashflows_share_persisted_intent(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    result = trade.add_trade(db.get_record(key), 100.5)
    assert result.requested == result.filled == 0.03  # .037 desired -> 3 contracts of .01
    assert result.avg_price == 100.1  # ask + adverse slippage, tick-size rounded
    history = db.get_order_history(key)
    assert history["attempts"][0]["identity"]["contract_complete"] is True
    contract = history["attempts"][0]["identity"]["order_contract"]
    assert contract["schema"] == "chan-paper-order-v1" and contract["exchange_amount"] == "3"
    assert contract["paper_account"]["schema"] == "chan-linear-paper-v1"
    quote(trade, 1002, bid="110", ask="110.1", mark="110")
    trade.apply_sim_funding(CODE, at_ms=1002, rate="0.01", mark_price="110", event_id="f1")
    result = trade.cover_trade(db.get_record(key), None, "market reduction")
    assert result.avg_price == 109.8
    report = trade.get_sim_account_report()
    assert Decimal(report["account"]["snapshot"]["cash"]) == Decimal("1000.251703")
    assert db.get_record(key)["current_qty"] == 0
    assert trade.exchange is None


def test_partial_fills_use_current_quote_and_restart_does_not_double_book_fees(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    client = trade.make_client_order_id(db.get_record(key), "open")
    trade.set_sim_fill_plan(client, [0, 0.01, 0.03])
    result = trade.add_trade(db.get_record(key), 102)
    assert result.filled == 0
    quote(trade, 1002, bid="100.9", ask="101", mark="101")
    restarted = paper_engine(db, state=trade.sim_state)
    restarted.restore()
    assert db.get_record(key)["current_qty"] == 0.01
    assert db.get_record(key)["open_price"] == 101.2
    quote(restarted, 1003, bid="101.9", ask="102", mark="102")
    restarted.restore()
    assert db.get_record(key)["current_qty"] == 0.03
    assert db.get_record(key)["open_price"] == pytest.approx((0.01*101.2+0.02*102)/0.03)
    before = restarted.get_sim_account_report()
    restarted.restore()
    assert restarted.get_sim_account_report() == before
    assert len(restarted.sim_state.orders) == 1
    assert len([e for e in before["account"]["events"] if e["event"]["kind"] == "open"]) == 2


def test_limit_and_post_only_wait_for_touch_and_cancel_remains_terminal(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001, bid="101.9", ask="102", mark="102")
    key = db.add_signal(make_signal(code=CODE))
    record = db.get_record(key)
    amount, price, contract = trade.prepare_order(CODE, 0.03, 100, record=record, post_only=True)
    client = trade.make_client_order_id(record, "open")
    assert db.acquire_open_intent(key, amount, client, order_contract=contract)
    result = trade.place_order(CODE, True, amount, price, client_order_id=client, post_only=True)
    assert result.filled == 0 and result.status == "open"
    quote(trade, 1002, bid="99.8", ask="99.9", mark="100")
    result = trade.query_order(CODE, result.order_id, client_order_id=client)
    assert result.filled == 0.03 and result.avg_price == 100
    assert Decimal(trade.get_sim_account_report()["account"]["snapshot"]["fees"]) == Decimal("0.0006")
    assert trade.cancel_order(CODE, result.order_id) is True
    assert trade.query_order(CODE, result.order_id, client_order_id=client).status == "closed"


def test_hedged_records_preserve_both_legs_even_when_net_position_is_zero(store):
    db, _ = store
    trade = paper_engine(db, account=paper_account(mode="hedged"))
    quote(trade, 1001)
    long_key = db.add_signal(make_signal(code=CODE))
    short_key = db.add_signal(make_signal(code=CODE, is_buy=False))
    trade.add_trade(db.get_record(long_key), 100.5)
    trade.add_trade(db.get_record(short_key), 99.5)
    assert db.get_record(long_key)["position_side"] == "LONG"
    assert db.get_record(short_key)["position_side"] == "SHORT"
    assert trade.get_position(CODE) == 0
    snapshot = trade.get_sim_account_report()["account"]["snapshot"]
    assert Decimal(snapshot["gross_notional"]) == 6 and Decimal(snapshot["margin_used"]) == 2
    assert len(snapshot["positions"]) == 2


def test_low_level_paper_submission_requires_real_db_intent_and_never_creates_session(store):
    trade = paper_engine(store[0])
    quote(trade, 1001)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, 0.03, 100.5, client_order_id="no-intent")
    assert trade.sim_state.orders == {} and trade.exchange is None


def test_another_paper_account_cannot_claim_original_intent_after_state_loss(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    record = db.get_record(key)
    amount, price, contract = trade.prepare_order(CODE, 0.03, 100.5, record=record)
    client = trade.make_client_order_id(record, "open")
    db.acquire_open_intent(key, amount, client, order_contract=contract)
    from Trade.LinearPaperAccount import CLinearPaperAccount
    original = paper_account(mode="one_way")
    other_account = CLinearPaperAccount(original.config, markets=list(original.markets.values()),
        position_mode="one_way", start_ms=1000, identity_seed="another-server")
    other = paper_engine(db, account=other_account)
    quote(other, 1001)
    with pytest.raises(CChanException):
        other.place_order(CODE, True, amount, price, client_order_id=client)
    assert db.get_record(key)["open_order_status"] == "created"
    assert other.sim_state.orders == {}


@pytest.mark.parametrize("field,value", [("quantity_unit", "contracts"), ("exchange_amount", "0.03"),
    ("contractSize", "0.1"), ("position_side", "SHORT"), ("margin_mode", "native_cross"),
    ("account_observation", {"hedged": False}), ("unknown", "not-a-supported-field")])
def test_resealed_paper_contract_cannot_claim_with_inconsistent_units_or_semantics(store, field, value):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    record = db.get_record(key)
    amount, price, contract = trade.prepare_order(CODE, 0.03, 100.5, record=record)
    if field == "contractSize":
        contract["market"][field] = value
    elif field in {"position_side", "margin_mode"}:
        contract["execution"][field] = value
    else:
        contract[field] = value
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    client = trade.make_client_order_id(record, "open")
    db.acquire_open_intent(key, amount, client, order_contract=contract)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, amount, price, client_order_id=client)
    assert db.get_record(key)["open_order_status"] == "created"
    assert trade.sim_state.orders == {}


def test_fee_after_full_requested_margin_shortfall_is_rejected_before_intent(store):
    db, _ = store
    trade = paper_engine(db, account=paper_account(mode="one_way", initial="3", leverage="1"))
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(db.get_record(key), 100.5)
    assert db.get_record(key)["open_attempt"] == 0
    assert trade.sim_state.orders == {}


def test_lost_ack_recovers_from_same_paper_server_without_second_order_or_fee(store, monkeypatch):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    ack = db.record_order_ack

    def unavailable(*args, **kwargs):
        raise CChanException("fake local crash after paper exchange accepted", 1)

    monkeypatch.setattr(db, "record_order_ack", unavailable)
    with pytest.raises(CChanException):
        trade.add_trade(db.get_record(key), 100.5)
    assert db.get_record(key)["open_order_id"] is None
    before = trade.get_sim_account_report()
    monkeypatch.setattr(db, "record_order_ack", ack)
    restarted = paper_engine(db, state=trade.sim_state)
    restarted.restore()
    assert db.get_record(key)["current_qty"] == 0.03
    assert len(restarted.sim_state.orders) == 1
    assert restarted.get_sim_account_report() == before


def test_paper_state_cannot_mix_prior_legacy_orders_or_silently_accept_price_without_mark_clock(store):
    db, _ = store
    trade = paper_engine(db)
    with pytest.raises(CChanException):
        trade.set_sim_price(CODE, 100)


def test_partial_close_cancel_retry_only_consumes_remaining_lots_and_charges_once(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 100.5)
    quote(trade, 1002, bid="110", ask="110.1", mark="110")
    first_client = trade.make_client_order_id(db.get_record(key), "close")
    trade.set_sim_fill_plan(first_client, [0, 0.01])
    trade.cover_trade(db.get_record(key), 110, "partial")
    restarted = paper_engine(db, state=trade.sim_state)
    restarted.restore()
    assert db.get_record(key)["current_qty"] == 0.02
    restarted.poll_orders(times=1, interval=0, adjust_price=True)
    assert db.get_record(key)["current_qty"] == 0
    assert db.get_record(key)["cover_attempt"] == 2
    assert db.get_record(key)["cover_client_order_id"] != first_client
    assert len(restarted.sim_state.orders) == 3
    assert db.get_record(key)["cover_order_avg_price"] == 109.8  # market retry, not the old limit 110
    assert Decimal(restarted.get_sim_account_report()["account"]["snapshot"]["fees"]) == sum(map(Decimal, ["0.003003", "0.0011", "0.002196"]))
    before = restarted.get_sim_account_report()
    restarted.restore()
    assert restarted.get_sim_account_report() == before


def test_shared_paper_account_handle_keeps_actual_fills_after_engine_commit(store):
    db, _ = store
    account = paper_account(mode="one_way")
    trade = paper_engine(db, account=account)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 100.5)
    assert trade.sim_state.paper_account is account
    assert account.position_quantity(f"{db.table}:{key}") == Decimal("0.03")


def test_legacy_simulated_orders_cannot_be_relabelled_as_full_paper_account(store):
    db, _ = store
    legacy = CCCXTTradeEngine(db, ccxt_conf={"mode": "dry_run", "default_type": "swap"},
        trade_conf={}, environ={}, push_msg=False)
    legacy.place_order(CODE, True, 0.03, 100, client_order_id="legacy-sim")
    legacy.sim_state.paper_account = paper_account(mode="one_way")
    with pytest.raises(CChanException):
        paper_engine(db, state=legacy.sim_state)


@pytest.mark.parametrize("field,value", [("requested", 0.04), ("filled", 0.02), ("avg_price", 99), ("status", "open")])
def test_paper_query_checks_actual_fill_ledger_instead_of_trusting_mutable_result(store, field, value):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    result = trade.add_trade(db.get_record(key), 100.5)
    setattr(trade.sim_state.orders[result.order_id], field, value)
    with pytest.raises(CChanException):
        trade.query_order(CODE, result.order_id, client_order_id=result.client_order_id)


def test_margin_collapse_rejects_later_partial_without_consuming_or_charging_it(store):
    db, _ = store
    trade = paper_engine(db, account=paper_account(mode="one_way", initial="3.1", leverage="1"))
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    client = trade.make_client_order_id(db.get_record(key), "open")
    trade.set_sim_fill_plan(client, [0.01, 0.03])
    trade.add_trade(db.get_record(key), 110)
    before = trade.get_sim_account_report()
    quote(trade, 1002, bid="109.9", ask="110", mark="110")
    trade.restore()
    assert db.get_record(key)["open_order_status"] == "rejected"
    assert db.get_record(key)["current_qty"] == 0.01
    assert trade.get_sim_account_report()["account"]["snapshot"]["fees"] == before["account"]["snapshot"]["fees"]


def test_stressed_paper_account_blocks_new_risk_but_allows_original_record_reduction(store):
    db, _ = store
    account = paper_account(mode="one_way", initial="3.1", leverage="1")
    trade = paper_engine(db, account=account)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 100.5)
    quote(trade, 1002)
    trade.apply_sim_funding(CODE, at_ms=1002, rate="0.9", mark_price="100", event_id="stress")
    quote(trade, 1003, bid="0.9", ask="1.1", mark="1")
    assert trade.get_sim_account_report()["account"]["snapshot"]["status"] == "liquidation_required"
    other_key = db.add_signal(make_signal(code=CODE, is_buy=False))
    with pytest.raises(CChanException):
        trade.add_trade(db.get_record(other_key), 1)
    assert db.get_record(other_key)["open_attempt"] == 0
    trade.cover_trade(db.get_record(key), None, "real loss exit")
    assert db.get_record(key)["current_qty"] == 0
    assert Decimal(trade.get_sim_account_report()["account"]["snapshot"]["cash"]) < 0


def test_minimum_price_tick_does_not_turn_reduce_only_exit_into_zero_price(store):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 100.5)
    quote(trade, 1002, bid="0.1", ask="0.2", mark="0.1")
    result = trade.cover_trade(db.get_record(key), None, "minimum ladder exit")
    assert result.status == "closed" and result.avg_price == 0.1
    assert db.get_record(key)["current_qty"] == 0


def test_low_level_contract_cannot_bypass_min_notional_by_resealing_quantity(store):
    from .test_linear_paper_account import paper_market
    from Trade.LinearPaperAccount import CLinearPaperAccount
    template = paper_account(mode="one_way")
    definition = paper_market()
    definition["min_notional"] = "3"
    account = CLinearPaperAccount(template.config, markets=[definition], position_mode="one_way", start_ms=1000, identity_seed="min-cost")
    db, _ = store
    trade = paper_engine(db, account=account)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    record = db.get_record(key)
    _, price, contract = trade.prepare_order(CODE, 0.03, 100.5, record=record)
    contract.update(quantity="0.01", exchange_amount="1", notional="1.005")
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    client = trade.make_client_order_id(record, "open")
    db.acquire_open_intent(key, 0.01, client, order_contract=contract)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, 0.01, price, client_order_id=client)
    assert db.get_record(key)["open_order_status"] == "created"


@pytest.mark.parametrize("plan", [[0.015], [0.01, 0.025]])
def test_bad_fill_plan_is_refused_before_claim_not_reported_as_an_exchange_rejection(store, plan):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    client = trade.make_client_order_id(db.get_record(key), "open")
    with pytest.raises(CChanException):
        trade.set_sim_fill_plan(client, plan)
        trade.add_trade(db.get_record(key), 100.5)
    assert db.get_record(key)["open_order_status"] in {None, "created"}
    assert trade.sim_state.orders == {}


@pytest.mark.parametrize("value", [True, False])
def test_fill_plan_bool_is_not_a_numeric_partial_quantity(store, value):
    trade = paper_engine(store[0])
    with pytest.raises(CChanException):
        trade.set_sim_fill_plan("intent", [value])


def test_orphan_legacy_server_order_cannot_hide_outside_order_state_map(store):
    from Trade.TradeEngine import COrderResult
    state = CSimExchangeState(paper_account=paper_account(mode="one_way"))
    state.orders["orphan"] = COrderResult(order_id="orphan", filled=0, requested=0.03, avg_price=None, status="open")
    with pytest.raises(CChanException):
        paper_engine(store[0], state=state)


def test_cached_client_result_does_not_ignore_wrong_leg_in_a_repeated_request(store):
    db, _ = store
    trade = paper_engine(db, account=paper_account(mode="hedged"))
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    result = trade.add_trade(db.get_record(key), 100.5)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, 0.03, 100.5, client_order_id=result.client_order_id, position_side="SHORT")


@pytest.mark.parametrize("damage", ["same_identity_lost_server", "db_quantity_drift"])
def test_new_risk_stops_if_existing_db_and_paper_fill_lots_cannot_be_reconciled(store, damage):
    db, _ = store
    trade = paper_engine(db)
    quote(trade, 1001)
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 100.5)
    if damage == "same_identity_lost_server":
        # Same declared identity/config is not a copy of the original exchange
        # state. Empty memory must never silently become a new funded account.
        trade = paper_engine(db)
        quote(trade, 1001)
    else:
        db.db.execute("UPDATE chan_trade SET current_qty=99 WHERE id=?", (key,))
    other = db.add_signal(make_signal(code=CODE))
    before = trade.get_sim_account_report()
    with pytest.raises(CChanException):
        trade.add_trade(db.get_record(other), 100.5)
    assert db.get_record(other)["open_attempt"] == 0
    assert trade.get_sim_account_report() == before
