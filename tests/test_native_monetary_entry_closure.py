"""Close direct new risk; historical v3 bytes never confer new permission."""
import hashlib
import json

import pytest

from . import test_crypto_order_contract as legacy_fixture

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_crypto_order_contract import CODE, order_db
from .test_crypto_venue_parameters import venue_engine
from .test_m6_trade import make_signal


AT = 1792972800000

LEGACY_V3_REFERENCE_SHA256 = {
    "binance|one_way|cross|buy": "26ca34a9f4e2e86c2543f53fc4ce6a59a629d32191241030e8050fb0fef1b63e",
    "okx|one_way|cross|buy": "a7f33a47d7f0a694631d263af4e7b71b6764626643f06314c034e9238002848d",
    "binance|hedged|cross|buy": "29e27797efdf0277da35049974dc34487ebc5b8267f9fca80ff51025980d8d22",
    "okx|hedged|cross|buy": "60fff6ef4f2431f73f0f27f15ae53d2d60270f21c628c060370d4a3e9483f752",
    "binance|one_way|isolated|buy": "25c3889171964db2b8086c93897c9a1caed38c66aac32b2a2c65c53be3928dba",
    "okx|one_way|isolated|buy": "85ad2bef59abf7139fea4e5e8d418badbb8b7a37c066e75cc9dd7011644191f5",
    "binance|hedged|isolated|buy": "42d1f39426037723b4583e5ff9e2a061d535a924e6dcf058db5f68808ac2fe2d",
    "okx|hedged|isolated|buy": "d7ba917c15c74e9f931e3658ef115f1e70f11c599f7f0f5e05b973cf5b430c33",
    "binance|one_way|cross|sell": "c07662ac181872e873bea822a69526aafb8fa575d8ebf9e1f0622ab0b946d2d2",
    "okx|one_way|cross|sell": "7531d372bb6acc8181cfb179348b8c3752c8de9b0abce6ad8e4a380d882cb4c6",
    "binance|hedged|cross|sell": "68fa2fe3fe2656a5fb40517897bc622413ec6335009671f837ba1ee00c515fc6",
    "okx|hedged|cross|sell": "1e84ad7512497acaad8d80aa241e45c8caa5f8efbb2b66605b5338d1c9075f73",
    "binance|one_way|isolated|sell": "d9562336a62632de192e8e80e76e0d0893e0afe453b461c76cbab4fed540ade9",
    "okx|one_way|isolated|sell": "491075e951c0beecad3316c026e290278999c5bb34f190a2c2a991834b26a3d5",
    "binance|hedged|isolated|sell": "5ce07ff6c7d8d312fc0ed3907f7c05df2d1e5430aaacfea8e8459b8fe569d678",
    "okx|hedged|isolated|sell": "781ba29c2344d147fdb028bcd386a5ccf8b16004bb9a5466b43e960dbceacdf3",
}


def fixed_legacy_clock(monkeypatch):
    for module in ("Trade.TradeEngine", "Trade.db_util", "Trade.OrderAudit", "tests.test_crypto_order_contract"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: AT)
    monkeypatch.setattr("Trade.db_util.now_str", lambda: "2026-10-26 00:00:00")


def legacy_bytes(trade, record_id, result):
    return canonical_bytes({"records": trade.chan_db.query_all(), "history": trade.chan_db.get_order_history(record_id),
        "result": vars(result), "server_orders": trade.exchange.orders, "created": trade.exchange.created,
        "native_requests": trade.exchange.native_requests})


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode", ["one_way", "hedged"])
@pytest.mark.parametrize("margin", ["cross", "isolated"])
@pytest.mark.parametrize("is_buy", [True, False])
def test_historical_v3_fixture_preserves_original_public_reference_bytes(order_db, tmp_path, monkeypatch, venue, mode, margin, is_buy):
    fixed_legacy_clock(monkeypatch)
    trade = venue_engine(order_db, tmp_path, venue, mode, margin)
    key = order_db.add_signal(make_signal(code=CODE, is_buy=is_buy))
    original = getattr(legacy_fixture, "open_legacy_history", None)
    assert callable(original), "a fake-only historical constructor, not a new-risk admission bypass, is required"
    result = original(trade, order_db.get_record(key), 100)
    row = order_db.get_record(key)
    assert json.loads(row["open_order_contract"])["schema"] == "chan-ccxt-order-v3"
    assert result.filled == .01 and row["open_requested_qty"] == .03
    assert row["open_order_status"] == "open" and len(trade.exchange.created) == 1
    digest = hashlib.sha256(legacy_bytes(trade, key, result)).hexdigest()
    assert digest == LEGACY_V3_REFERENCE_SHA256[f"{venue}|{mode}|{margin}|{'buy' if is_buy else 'sell'}"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode", ["one_way", "hedged"])
@pytest.mark.parametrize("margin", ["cross", "isolated"])
@pytest.mark.parametrize("is_buy", [True, False])
def test_default_swap_without_guard_cannot_reach_quota_sdk_or_intent(order_db, tmp_path, monkeypatch, venue, mode, margin, is_buy):
    trade = venue_engine(order_db, tmp_path, venue, mode, margin)
    key = order_db.add_signal(make_signal(code=CODE, is_buy=is_buy))
    original, quota_calls = trade.quota_gen.get_quota, []
    def counted(*args, **kwargs):
        quota_calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(trade.quota_gen, "get_quota", counted)
    with pytest.raises(CChanException, match="原生新风险"):
        trade.add_trade(order_db.get_record(key), 100)
    assert quota_calls == [] and trade.exchange.created == []
    assert trade.exchange.account_reads == [] and trade.exchange.native_requests == []
    assert order_db.get_record(key)["open_attempt"] == 0


@pytest.mark.parametrize("backend", ["sqlite", "mysql"])
@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("flip_paper_flag", [False, True])
def test_plain_v3_created_intent_is_not_new_money_admission_for_public_send(order_db, tmp_path, monkeypatch, backend, venue, flip_paper_flag):
    trade = venue_engine(order_db, tmp_path, venue)
    key = order_db.add_signal(make_signal(code=CODE))
    record = order_db.get_record(key)
    quantity, price, contract = trade.prepare_order(CODE, .03, 100, record=record)
    client_id = trade.make_client_order_id(record, "open")
    assert order_db.acquire_open_intent(key, quantity, client_id, order_contract=contract)
    if flip_paper_flag:
        original = order_db.get_order_intent
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            trade.dry_run = True
            return result
        monkeypatch.setattr(order_db, "get_order_intent", changed)
    with monkeypatch.context() as scoped:
        scoped.setattr(order_db, "db_type", backend)
        with pytest.raises(CChanException, match="原生.*新风险"):
            trade.place_order(CODE, True, quantity, price, client_order_id=client_id, position_side="BOTH")
    assert trade.exchange.created == []
    assert order_db.get_record(key)["open_order_status"] == "created"
