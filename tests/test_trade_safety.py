import json
from pathlib import Path

import pytest

from Common.ChanException import CChanException, ErrCode
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB


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
