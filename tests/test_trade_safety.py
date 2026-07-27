import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from Common.ChanException import CChanException, ErrCode
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB
from Trade.TradeEngine import COrderResult


REPO_ROOT = Path(__file__).resolve().parents[1]
REJECTED_V5 = (
    REPO_ROOT
    / "ModelStrategy"
    / "research"
    / "baselines"
    / "freeze_v5_candidate_v1_is.json"
)


@pytest.fixture()
def trade_db(tmp_path):
    db = CChanDB(
        db_conf={
            "type": "sqlite",
            "sqlite_path": str(tmp_path / "trade.db"),
        }
    )
    yield db
    db.close()


def write_candidate_receipt(tmp_path):
    path = tmp_path / "candidate-receipt.json"
    path.write_text(
        json.dumps(
            {
                "status": "candidate",
                "strategy_id": "approved-strategy",
                "spec_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def enabled_trade_conf(receipt):
    return {
        "strategy_receipt": str(receipt),
        "strategy_id": "approved-strategy",
        "strategy_spec_hash": "a" * 64,
    }


def test_api_credentials_alone_never_leave_dry_run(trade_db):
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={"api_key": "secret-key", "secret": "secret-value"},
        trade_conf={},
        environ={},
        push_msg=False,
    )
    assert engine.mode == "dry_run"
    assert engine.dry_run is True
    assert engine.exchange is None


def test_unknown_mode_fails_closed_without_echoing_secrets(trade_db):
    with pytest.raises(CChanException) as caught:
        CCCXTTradeEngine(
            trade_db,
            ccxt_conf={
                "mode": "automatic",
                "api_key": "do-not-print-key",
                "secret": "do-not-print-secret",
            },
            trade_conf={},
            environ={},
            push_msg=False,
        )
    assert caught.value.errcode == ErrCode.TRADE_UNLOCK_FAIL
    assert "do-not-print" not in str(caught.value)


def test_tracked_rejected_v5_receipt_blocks_testnet(trade_db):
    with pytest.raises(CChanException, match="策略收据") as caught:
        CCCXTTradeEngine(
            trade_db,
            ccxt_conf={
                "mode": "testnet",
                "testnet": True,
                "api_key": "key",
                "secret": "secret",
            },
            trade_conf={"strategy_receipt": str(REJECTED_V5)},
            environ={"CHANPY_ENABLE_TESTNET": "YES"},
            push_msg=False,
        )
    assert caught.value.errcode == ErrCode.TRADE_UNLOCK_FAIL


def test_testnet_requires_candidate_receipt_and_explicit_environment_unlock(
    trade_db, tmp_path
):
    receipt = write_candidate_receipt(tmp_path)
    ccxt_conf = {
        "mode": "testnet",
        "testnet": True,
        "api_key": "key",
        "secret": "secret",
    }
    with pytest.raises(CChanException, match="CHANPY_ENABLE_TESTNET"):
        CCCXTTradeEngine(
            trade_db,
            ccxt_conf=ccxt_conf,
            trade_conf=enabled_trade_conf(receipt),
            environ={},
            push_msg=False,
        )
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf=ccxt_conf,
        trade_conf=enabled_trade_conf(receipt),
        environ={"CHANPY_ENABLE_TESTNET": "YES"},
        push_msg=False,
    )
    assert engine.mode == "testnet"
    assert engine.dry_run is False
    assert engine.exchange is None


def test_empty_optional_receipt_matches_do_not_block_testnet(trade_db, tmp_path):
    receipt = write_candidate_receipt(tmp_path)
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={
            "mode": "testnet",
            "testnet": True,
            "api_key": "key",
            "secret": "secret",
        },
        trade_conf={
            "strategy_receipt": str(receipt),
            "strategy_id": "",
            "strategy_spec_hash": "",
        },
        environ={"CHANPY_ENABLE_TESTNET": "YES"},
        push_msg=False,
    )
    assert engine.mode == "testnet"


def test_live_requires_exact_unlock_and_non_testnet_configuration(
    trade_db, tmp_path
):
    receipt = write_candidate_receipt(tmp_path)
    trade_conf = enabled_trade_conf(receipt)
    base = {
        "mode": "live",
        "testnet": False,
        "api_key": "key",
        "secret": "secret",
    }
    with pytest.raises(CChanException, match="CHANPY_LIVE_TRADING_UNLOCK"):
        CCCXTTradeEngine(
            trade_db,
            ccxt_conf=base,
            trade_conf=trade_conf,
            environ={},
            push_msg=False,
        )
    with pytest.raises(CChanException, match="testnet"):
        CCCXTTradeEngine(
            trade_db,
            ccxt_conf={**base, "testnet": True},
            trade_conf=trade_conf,
            environ={
                "CHANPY_LIVE_TRADING_UNLOCK": "I_ACCEPT_REAL_ORDERS"
            },
            push_msg=False,
        )
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf=base,
        trade_conf=trade_conf,
        environ={"CHANPY_LIVE_TRADING_UNLOCK": "I_ACCEPT_REAL_ORDERS"},
        push_msg=False,
    )
    assert engine.mode == "live"
    assert engine.exchange is None


def test_kill_switch_is_rechecked_before_non_dry_order(trade_db, tmp_path):
    receipt = write_candidate_receipt(tmp_path)
    environ = {"CHANPY_ENABLE_TESTNET": "YES"}
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={
            "mode": "testnet",
            "testnet": True,
            "api_key": "key",
            "secret": "secret",
        },
        trade_conf=enabled_trade_conf(receipt),
        environ=environ,
        push_msg=False,
    )
    environ["CHANPY_KILL_SWITCH"] = "1"
    with pytest.raises(CChanException, match="KILL_SWITCH") as caught:
        engine.place_order("BTC/USDT", True, 0.001, 50000.0)
    assert caught.value.errcode == ErrCode.TRADE_UNLOCK_FAIL
    assert engine.exchange is None


def test_order_result_rejects_unknown_status():
    with pytest.raises(CChanException, match="订单状态"):
        COrderResult(
            order_id="order-1",
            requested=1.0,
            filled=0.0,
            avg_price=None,
            status="partially_filled",
            client_order_id="client-1",
        )


def test_dry_run_fill_plan_advances_monotonically(trade_db):
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={"mode": "dry_run", "default_type": "spot"},
        trade_conf={},
        environ={},
        push_msg=False,
    )
    engine.set_sim_fill_plan("open-1", [0.0, 4.0, 10.0])

    placed = engine.place_order(
        "TEST/USDT",
        True,
        10.0,
        100.0,
        client_order_id="open-1",
    )
    assert placed.requested == 10.0
    assert placed.filled == 0.0
    assert placed.status == "open"
    assert placed.client_order_id == "open-1"
    assert engine.get_position("TEST/USDT") == 0.0

    partial = engine.query_order("TEST/USDT", placed.order_id)
    assert partial.requested == 10.0
    assert partial.filled == 4.0
    assert partial.status == "open"
    assert engine.get_position("TEST/USDT") == 4.0

    closed = engine.query_order("TEST/USDT", placed.order_id)
    assert closed.filled == 10.0
    assert closed.status == "closed"
    assert engine.get_position("TEST/USDT") == 10.0

    repeated = engine.query_order("TEST/USDT", placed.order_id)
    assert repeated.filled == 10.0
    assert engine.get_position("TEST/USDT") == 10.0


def test_dry_run_rejects_market_post_only_and_spot_oversell(trade_db):
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={"mode": "dry_run", "default_type": "spot"},
        trade_conf={},
        environ={},
        push_msg=False,
    )
    with pytest.raises(CChanException, match="post-only"):
        engine.place_order(
            "TEST/USDT", True, 1.0, None, post_only=True
        )

    engine.place_order("TEST/USDT", True, 5.0, 100.0)
    with pytest.raises(CChanException, match="超卖") as caught:
        engine.place_order("TEST/USDT", False, 5.1, 100.0)
    assert caught.value.errcode == ErrCode.QUOTA_NOT_ENOUGH
    assert engine.get_position("TEST/USDT") == 5.0


def test_dry_run_contract_reduce_only_cannot_increase_or_flip(trade_db):
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={
            "mode": "dry_run",
            "default_type": "swap",
            "leverage": 2,
            "position_side": "BOTH",
        },
        trade_conf={},
        environ={},
        push_msg=False,
    )
    engine.place_order("BTC/USDT:USDT", True, 3.0, 100.0)
    assert engine.get_position("BTC/USDT:USDT") == 3.0

    with pytest.raises(CChanException, match="reduce-only"):
        engine.place_order(
            "BTC/USDT:USDT", True, 1.0, 100.0, reduce_only=True
        )
    with pytest.raises(CChanException, match="穿仓"):
        engine.place_order(
            "BTC/USDT:USDT", False, 3.1, 100.0, reduce_only=True
        )

    closed = engine.place_order(
        "BTC/USDT:USDT",
        False,
        3.0,
        100.0,
        reduce_only=True,
        client_order_id="close-1",
        position_side="BOTH",
    )
    assert closed.status == "closed"
    assert engine.get_position("BTC/USDT:USDT") == 0.0


class FakeCCXTError(Exception):
    pass


class FakeContractExchange:
    def __init__(self):
        self.created = []
        self.leverage_calls = []
        self.positions_calls = []

    def amount_to_precision(self, code, amount):
        return str(amount)

    def price_to_precision(self, code, price):
        return str(price)

    def set_leverage(self, leverage, code, params=None):
        self.leverage_calls.append((leverage, code, params or {}))

    def create_order(self, code, order_type, side, amount, price=None, params=None):
        self.created.append((code, order_type, side, amount, price, params or {}))
        return {
            "id": "exchange-1",
            "clientOrderId": (params or {}).get("clientOrderId"),
            "amount": amount,
            "filled": 0.75,
            "average": 101.0,
            "status": "open",
        }

    def fetch_positions(self, symbols):
        self.positions_calls.append(symbols)
        return [
            {"symbol": symbols[0], "side": "long", "contracts": 3.0},
            {"symbol": symbols[0], "side": "short", "contracts": 1.0},
        ]

    def fetch_balance(self):
        raise AssertionError("合约持仓不能从现货余额推导")


def test_contract_order_passes_explicit_intent_and_queries_positions(
    trade_db, tmp_path, monkeypatch
):
    receipt = write_candidate_receipt(tmp_path)
    engine = CCCXTTradeEngine(
        trade_db,
        ccxt_conf={
            "mode": "testnet",
            "testnet": True,
            "api_key": "key",
            "secret": "secret",
            "default_type": "swap",
            "leverage": 3,
            "position_side": "LONG",
        },
        trade_conf=enabled_trade_conf(receipt),
        environ={"CHANPY_ENABLE_TESTNET": "YES"},
        push_msg=False,
    )
    exchange = FakeContractExchange()
    engine.exchange = exchange
    monkeypatch.setitem(
        sys.modules, "ccxt", SimpleNamespace(BaseError=FakeCCXTError)
    )

    result = engine.place_order(
        "BTC/USDT:USDT",
        False,
        2.0,
        101.0,
        client_order_id="close-42",
        reduce_only=True,
        post_only=True,
        position_side="LONG",
    )

    assert result.requested == 2.0
    assert result.filled == 0.75
    assert result.status == "open"
    assert result.client_order_id == "close-42"
    assert exchange.leverage_calls == [
        (3, "BTC/USDT:USDT", {"positionSide": "LONG"})
    ]
    assert exchange.created == [
        (
            "BTC/USDT:USDT",
            "limit",
            "sell",
            2.0,
            101.0,
            {
                "clientOrderId": "close-42",
                "reduceOnly": True,
                "postOnly": True,
                "positionSide": "LONG",
            },
        )
    ]
    assert engine.get_position("BTC/USDT:USDT") == 2.0
    assert exchange.positions_calls == [["BTC/USDT:USDT"]]
