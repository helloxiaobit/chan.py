"""协议参数用真实 CCXT request builder 验证；所有账户/订单 I/O 均为 fake。"""
import copy
import hashlib
import json
import re

import ccxt
import pytest
from CustomBuySellPoint.Decision import canonical_bytes

from Common.ChanException import CChanException
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from .test_crypto_order_contract import CODE, COfflineExchange, market, open_pre_journal_copy, order_db
from .test_m6_trade import make_signal
from .test_trade_safety import enabled_trade_conf, write_candidate_receipt


class CVenueExchange(COfflineExchange):
    def __init__(self, venue, *, mode="one_way", margin="cross", leverage=3, spot=False):
        definition = market(spot=spot)
        definition["baseId"], definition["quoteId"], definition["settleId"] = "TEST", "USDT", "USDT"
        definition["info"] = {"orderTypes": ["LIMIT", "MARKET", "LIMIT_MAKER"]}
        if venue == "okx":
            definition["id"] = "TEST-USDT" if spot else "TEST-USDT-SWAP"
        super().__init__(definition)
        self.id, self.mode, self.margin, self.leverage = venue, mode, margin, leverage
        self.builder = getattr(ccxt, venue)({"options": {"defaultType": "spot" if spot else "swap"}})
        self.builder.set_sandbox_mode(True)
        self.urls, self.headers = copy.deepcopy(self.builder.urls), copy.deepcopy(self.builder.headers)
        self.hostname = self.builder.hostname
        self.builder.set_markets([definition])
        self.native_requests, self.account_reads = [], []

    def fetch_position_mode(self, symbol=None, params=None):
        self.account_reads.append(("mode", symbol, params))
        return {"hedged": self.mode == "hedged", "info": {}}

    def fetch_leverage(self, symbol, params=None):
        self.account_reads.append(("leverage", symbol, params))
        return {"symbol": symbol, "marginMode": self.margin, "longLeverage": self.leverage,
                "shortLeverage": self.leverage, "info": {}}

    def create_order(self, code, order_type, side, amount, price=None, params=None):
        native = self.builder.create_order_request(code, order_type, side, amount, price, copy.deepcopy(params or {}))
        self.native_requests.append(native)
        # The unit fixture's server is intentionally independent of native
        # spelling. Normalize only the known client-id alias for its report.
        fake_params = {**params, "clientOrderId": params.get("clientOrderId") or params.get("clOrdId") or params.get("newClientOrderId")}
        return super().create_order(code, order_type, side, amount, price, fake_params)


def venue_engine(db, tmp_path, venue, mode="one_way", margin="cross", *, spot=False):
    exchange = CVenueExchange(venue, mode=mode, margin=margin, spot=spot)
    result = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(3.7),
        ccxt_conf={"exchange": venue, "mode": "testnet", "testnet": True, "api_key": "key", "secret": "secret",
                   "default_type": "spot" if spot else "swap", "position_mode": mode,
                   "margin_mode": margin, "leverage": 3},
        trade_conf=enabled_trade_conf(write_candidate_receipt(tmp_path)),
        environ={"CHANPY_ENABLE_TESTNET": "YES"}, push_msg=False)
    result.exchange, result.api_interval = exchange, 0
    return result


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode", ["one_way", "hedged"])
@pytest.mark.parametrize("margin", ["cross", "isolated"])
@pytest.mark.parametrize("is_buy", [True, False])
def test_native_open_and_reduce_requests_bind_the_correct_account_leg(order_db, tmp_path, venue, mode, margin, is_buy):
    trade = venue_engine(order_db, tmp_path, venue, mode, margin)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = order_db.add_signal(make_signal(code=CODE, is_buy=is_buy))
    opened = trade.add_trade(order_db.get_record(record_id), 100)
    assert opened.filled == pytest.approx(0.03)
    side = "BOTH" if mode == "one_way" else "LONG" if is_buy else "SHORT"
    assert order_db.get_record(record_id)["position_side"] == side
    assert trade.exchange.leverage_calls == []  # No silent account mutations.
    native = trade.exchange.native_requests[0]
    if venue == "binance":
        assert native["positionSide"] == side
        assert not native.get("reduceOnly", False)
    else:
        assert native["tdMode"] == margin
        assert native["posSide"] == ("net" if mode == "one_way" else side.lower())
        assert not native.get("reduceOnly", False)
        assert re.fullmatch(r"[A-Za-z0-9]{1,32}", native["clOrdId"])
    contract = json.loads(order_db.get_record(record_id)["open_order_contract"])
    assert contract["schema"] == "chan-ccxt-order-v3"
    assert contract["execution"]["position_mode"] == mode
    assert contract["execution"]["margin_mode"] == margin
    trade.cover_trade(order_db.get_record(record_id), 101, "native exit")
    close = trade.exchange.native_requests[-1]
    assert close["side"].lower() == ("sell" if is_buy else "buy")
    if venue == "binance":
        assert close["positionSide"] == side
    else:
        assert close["posSide"] == ("net" if mode == "one_way" else side.lower())
    if mode == "hedged":
        assert "reduceOnly" not in close
    else:
        assert close["reduceOnly"] is True
    assert order_db.get_record(record_id)["current_qty"] == 0


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("changed", [{"mode": "hedged"}, {"margin": "isolated"}, {"leverage": 9}])
def test_account_mismatch_refuses_new_risk_without_reconfiguring_or_claiming(order_db, tmp_path, venue, changed):
    trade = venue_engine(order_db, tmp_path, venue)
    for field, value in changed.items():
        setattr(trade.exchange, field, value)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert trade.exchange.created == [] and trade.exchange.leverage_calls == []
    assert order_db.get_record(record_id)["status"] == "signal"


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_existing_leg_can_reduce_after_global_config_and_leverage_change(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue, "hedged", "isolated")
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = order_db.add_signal(make_signal(code=CODE))
    trade.add_trade(order_db.get_record(record_id), 100)
    trade.ccxt_conf.update(position_mode="one_way", margin_mode="cross")
    trade.exchange.leverage = 9
    trade.cover_trade(order_db.get_record(record_id), 101, "still reduce original leg")
    request = trade.exchange.native_requests[-1]
    assert request.get("posSide", request.get("positionSide")) in {"long", "LONG"}
    assert order_db.get_record(record_id)["current_qty"] == 0


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_client_id_is_short_alphanumeric_stable_and_unique_across_attempts(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    record_id = order_db.add_signal(make_signal(code=CODE))
    record = order_db.get_record(record_id)
    token = trade.make_client_order_id(record, "open")
    assert re.fullmatch(r"[A-Za-z0-9]{1,32}", token)
    assert trade.make_client_order_id(record, "open") == token
    assert trade.make_client_order_id({**record, "open_attempt": 1}, "open") != token


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_post_only_reduce_limit_uses_the_native_maker_flag(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = order_db.add_signal(make_signal(code=CODE))
    trade.add_trade(order_db.get_record(record_id), 100)
    record = order_db.get_record(record_id)
    quantity, price, contract = trade.prepare_order(CODE, 0.03, 101, reduce_only=True, record=record, post_only=True)
    client_id = trade.make_client_order_id(record, "close")
    assert order_db.acquire_close_intent(record_id, quantity, client_id, "maker exit", order_contract=contract,
                                        previous_attempt=record["cover_attempt"])
    trade.place_order(CODE, False, quantity, price, reduce_only=True, post_only=True,
                      client_order_id=client_id, position_side="BOTH")
    native = trade.exchange.native_requests[-1]
    assert native.get("timeInForce") == "GTX" if venue == "binance" else native["ordType"] == "post_only"


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_spot_market_order_keeps_base_quantity_on_the_wire(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue, spot=True)
    trade.exchange.fill = 0.01
    code = "TEST/USDT"
    record_id = order_db.add_signal(make_signal(code=code))
    record = order_db.get_record(record_id)
    quantity, _, contract = trade.prepare_order(code, 0.03, None, record=record)
    client_id = trade.make_client_order_id(record, "open")
    assert order_db.acquire_open_intent(record_id, quantity, client_id, order_contract=contract)
    trade.place_order(code, True, quantity, None, client_order_id=client_id)
    native = trade.exchange.native_requests[-1]
    if venue == "binance":
        assert float(native["quantity"]) == pytest.approx(0.03) and "quoteOrderQty" not in native
    else:
        assert native["tdMode"] == "cash" and native["tgtCcy"] == "base_ccy" and native["banAmend"] is True
        assert float(native["sz"]) == pytest.approx(0.03) and "posSide" not in native


def replace_contract(db, record_id, contract):
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    db.db.execute("UPDATE chan_trade SET open_order_contract=? WHERE id=?", (canonical_bytes(contract).decode(), record_id))


@pytest.mark.parametrize("changed", ["missing_leg", "bool_leverage", "unknown_mode", "wrong_observed_mode", "missing_observation"])
def test_rehashed_execution_evidence_is_checked_during_restore(order_db, tmp_path, changed):
    trade = venue_engine(order_db, tmp_path, "okx")
    record_id = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(record_id), 100)
    contract = json.loads(order_db.get_record(record_id)["open_order_contract"])
    if changed == "missing_leg":
        del contract["execution"]["position_side"]
    elif changed == "bool_leverage":
        contract["execution"]["leverage"] = True
    elif changed == "unknown_mode":
        contract["execution"]["position_mode"] = "unknown"
    elif changed == "wrong_observed_mode":
        contract["account_observation"]["hedged"] = True
    else:
        contract["account_observation"] = None
    replace_contract(order_db, record_id, contract)
    with pytest.raises(CChanException):
        trade.query_order(CODE, order.order_id)


def test_v1_units_remain_readable_but_cannot_silently_supply_missing_execution_settings(order_db, tmp_path):
    trade = venue_engine(order_db, tmp_path, "okx")
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(record_id), 100)
    contract = json.loads(order_db.get_record(record_id)["open_order_contract"])
    contract["schema"] = "chan-ccxt-order-v1"
    del contract["execution"], contract["account_observation"], contract["post_only"], contract["account_context"]
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    record = order_db.get_record(record_id)
    record["open_order_contract"] = canonical_bytes(contract).decode()
    legacy = open_pre_journal_copy(tmp_path, record)
    try:
        trade.chan_db = legacy
        assert trade.query_order(CODE, order.order_id).filled == pytest.approx(0.03)
        with pytest.raises(CChanException):
            trade.cover_trade(legacy.get_record(record_id), 101, "v1 needs explicit execution migration")
        assert len(trade.exchange.created) == 1
    finally:
        legacy.close()


@pytest.mark.parametrize("method", ["fetch_position_mode", "fetch_leverage"])
def test_incomplete_account_read_is_a_closed_failure_before_intent(order_db, tmp_path, monkeypatch, method):
    trade = venue_engine(order_db, tmp_path, "okx")
    monkeypatch.setattr(trade.exchange, method, lambda *args, **kwargs: None)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert order_db.get_record(record_id)["status"] == "signal"
    assert trade.exchange.created == []


def test_account_read_failure_after_cas_is_reported_without_claim_or_submission(order_db, tmp_path, monkeypatch):
    trade = venue_engine(order_db, tmp_path, "okx")
    mode = trade.exchange.fetch_position_mode
    reads = []
    def interrupted(*args, **kwargs):
        reads.append(1)
        if len(reads) > 1:
            raise ccxt.NetworkError("synthetic private read interrupted")
        return mode(*args, **kwargs)
    monkeypatch.setattr(trade.exchange, "fetch_position_mode", interrupted)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert order_db.get_record(record_id)["open_order_status"] == "created"
    assert trade.exchange.created == []


def test_one_way_configuration_cannot_also_request_a_hedge_leg(order_db, tmp_path):
    trade = venue_engine(order_db, tmp_path, "binance")
    trade.position_side = "LONG"
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert order_db.get_record(record_id)["status"] == "signal"


def test_post_only_cannot_be_changed_after_the_intent_has_been_persisted(order_db, tmp_path):
    trade = venue_engine(order_db, tmp_path, "okx")
    record_id = order_db.add_signal(make_signal(code=CODE))
    record = order_db.get_record(record_id)
    quantity, price, contract = trade.prepare_order(CODE, 0.03, 100, record=record)
    client_id = trade.make_client_order_id(record, "open")
    assert order_db.acquire_open_intent(record_id, quantity, client_id, order_contract=contract)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, quantity, price, post_only=True, client_order_id=client_id)
    assert order_db.get_record(record_id)["open_order_status"] == "created"
    assert trade.exchange.created == []


@pytest.mark.parametrize("stop", ["kill", "unlock"])
@pytest.mark.parametrize("at", ["prepare", "read", "claim"])
def test_account_verification_cannot_outlive_revoked_order_authority(order_db, tmp_path, monkeypatch, stop, at):
    trade = venue_engine(order_db, tmp_path, "okx")
    leverage = trade.exchange.fetch_leverage
    reads = []
    def revoke():
        if stop == "kill":
            trade.safety_policy.environ["CHANPY_KILL_SWITCH"] = "1"
        else:
            trade.safety_policy.environ.pop("CHANPY_ENABLE_TESTNET")
    def revoke_after_second_read(*args, **kwargs):
        result = leverage(*args, **kwargs)
        reads.append(1)
        if (len(reads) == 2 and at == "read") or (len(reads) == 1 and at == "prepare"):
            revoke()
        return result
    monkeypatch.setattr(trade.exchange, "fetch_leverage", revoke_after_second_read)
    claim = order_db.claim_order_submission
    def revoke_after_claim(*args, **kwargs):
        result = claim(*args, **kwargs)
        if at == "claim":
            revoke()
        return result
    monkeypatch.setattr(order_db, "claim_order_submission", revoke_after_claim)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert trade.exchange.created == []
    stored = order_db.get_record(record_id)
    assert stored["open_order_status"] == ({"prepare": None, "read": "created", "claim": "submitting"}[at])
    if at == "prepare":
        assert stored["status"] == "signal"
