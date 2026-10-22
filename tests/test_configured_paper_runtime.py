"""Configured scripts must share an actual persistent paper server and raw inputs."""
import hashlib
import json
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Config.EnvConfig import CEnv
from Trade.PaperState import CPersistentPaperState
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from .test_execution_store import store
from .test_linear_paper_account import paper_account, CODE
from .test_linear_paper_engine import paper_engine
from .test_m6_trade import make_signal
import subprocess
import sys
import os

SOURCE = {"exchange": "binance", "market_type": "swap", "settle": "USDT", "price_type": "contract"}
ROOT = Path(__file__).resolve().parents[1]
CLI_WORKER = r'''
import importlib, sys
from Trade.Script import TradeRuntime
now = int(sys.argv[2])
TradeRuntime.utc_now_ms = lambda: now
module = importlib.import_module(sys.argv[1])
if hasattr(module, "utc_now_ms"):
    module.utc_now_ms = lambda: now
sys.exit(module.main())
'''


def publish_quotes(path, at=1001):
    payload = {"synthetic_only": True, "source": SOURCE, "at_ms": at,
        "quotes": [{"symbol": CODE, "bid": "99.9", "ask": "100", "mark": "100", "last": 100.0}]}
    document = {"schema": "chan-software-paper-quotes-v1", "payload": payload,
        "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}
    path.write_bytes(canonical_bytes(document))
    return document


@pytest.fixture()
def runtime(store, tmp_path):
    db, conf = store
    server, quotes = tmp_path/"server.json", tmp_path/"quotes.json"
    with CPersistentPaperState.create(server, account=paper_account(mode="one_way"), database=conf["sqlite_path"]):
        pass
    publish_quotes(quotes)
    config = {"db": conf, "ccxt": {"mode": "dry_run", "exchange": "binance", "default_type": "swap"},
        "offline_data": {"source_identity": SOURCE}, "notify": {"backend": "none"},
        "trade": {"bench_price": 3.7, "paper": {"server_path": str(server), "quote_path": str(quotes), "quote_max_age_ms": 10}}}
    path = tmp_path/"runtime.json"
    path.write_bytes(canonical_bytes(config))
    return db, path, config


def test_configured_lifecycle_reopens_original_partial_order_and_releases_writer(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, _ = runtime
    with configured_trade_engine(db, env=CEnv(str(path)), quota_gen=CBenchPriceQuotaGen(3.7), now_ms=lambda: 1001, push_msg=False) as engine:
        engine.api_interval = 0
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
        assert engine.add_trade(record, 102).filled == 0.01
        contract = json.loads(db.get_record(record["id"])["open_order_contract"])
        assert contract["schema"] == "chan-paper-order-v3" and contract["software_quote_max_age_ms"] == 10
        first = engine.sim_state
        assert engine.paper_inputs.prices(engine) == {CODE: 100.0}
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1002, push_msg=False) as engine:
        engine.api_interval = 0
        assert engine.sim_state is not first
        engine.restore()
        assert db.get_record(record["id"])["current_qty"] == 0.03 and len(engine.sim_state.orders) == 1
        assert engine.exchange is None


def test_missing_original_server_never_creates_one_or_falls_back(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, config = runtime
    server = Path(config["trade"]["paper"]["server_path"])
    server.unlink()
    with pytest.raises(CChanException):
        with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1001, push_msg=False):
            pass
    assert not server.exists()


@pytest.mark.parametrize("damage", ["expired", "changed", "missing"])
def test_unavailable_quote_stops_new_fills_and_risk_but_keeps_known_query_and_cancel(runtime, damage):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, config = runtime
    clock = [1001]
    with configured_trade_engine(db, env=CEnv(str(path)), quota_gen=CBenchPriceQuotaGen(3.7), now_ms=lambda: clock[0], push_msg=False) as engine:
        engine.api_interval = 0
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
        result = engine.add_trade(record, 102)
        before = engine.get_sim_account_report()
        quote_path = Path(config["trade"]["paper"]["quote_path"])
        if damage == "expired":
            clock[0] = 1012
        elif damage == "missing":
            quote_path.unlink()
        else:
            publish_quotes(quote_path, 1002)
        queried = engine.query_order(CODE, result.order_id, client_order_id=result.client_order_id)
        assert queried.filled == 0.01 and queried.status == "open"
        assert engine.get_sim_account_report() == before
        with pytest.raises(CChanException):
            engine.prepare_order(CODE, 0.03, 102, record=db.get_record(record["id"]))
        assert engine.cancel_order(CODE, result.order_id) is True
        assert engine.query_order(CODE, result.order_id).status == "canceled"
        assert engine.paper_inputs.issues and len(engine.sim_state.orders) == 1
        assert engine.get_sim_account_report() == before


def test_profile_cannot_claim_a_different_configured_venue(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, config = runtime
    config["ccxt"]["exchange"] = "okx"
    path.write_bytes(canonical_bytes(config))
    with pytest.raises(CChanException):
        with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1001, push_msg=False):
            pass


@pytest.mark.parametrize("damage", ["future", "old", "clock", "symbol", "duplicate", "synthetic", "bid", "tick", "mark", "last", "hash", "bytes"])
def test_actual_quote_semantics_are_required_even_with_a_resealed_digest(runtime, damage):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, config = runtime
    quotes = Path(config["trade"]["paper"]["quote_path"])
    document = json.loads(quotes.read_bytes())
    body, row = document["payload"], document["payload"]["quotes"][0]
    if damage in {"future", "old", "clock"}:
        body["at_ms"] = {"future": 1002, "old": 990, "clock": True}[damage]
    elif damage == "symbol":
        row["symbol"] = "FOREIGN/USDT:USDT"
    elif damage == "duplicate":
        body["quotes"].append(dict(row))
    elif damage == "synthetic":
        body["synthetic_only"] = False
    elif damage == "bid":
        row["bid"] = "101"
    elif damage == "tick":
        row["bid"] = "99.91"
    elif damage == "mark":
        row["mark"] = "NaN"
    elif damage == "last":
        row["last"] = False
    document["payload_sha256"] = "0"*64 if damage == "hash" else hashlib.sha256(canonical_bytes(body)).hexdigest()
    quotes.write_bytes(json.dumps(document, indent=2).encode() if damage == "bytes" else canonical_bytes(document))
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1001, push_msg=False) as engine:
        with pytest.raises(CChanException):
            engine.paper_inputs.prices(engine)
        assert engine.paper_inputs.issues and engine.get_sim_account_report()["effects"] == []


def test_quote_ages_are_checked_after_the_actual_reader_finishes(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, _ = runtime
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1001, push_msg=False) as engine:
        times = iter([1001, 1012])
        engine.paper_inputs.now_ms = lambda: next(times)
        with pytest.raises(CChanException):
            engine.paper_inputs.prices(engine)


@pytest.mark.parametrize("point", ["after_intent", "after_query_check", "before_actual_fill"])
def test_source_expiry_at_actual_submission_or_fill_boundary_never_creates_a_fill(runtime, monkeypatch, point):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, _ = runtime
    clock = [1001]
    with configured_trade_engine(db, env=CEnv(str(path)), quota_gen=CBenchPriceQuotaGen(3.7), now_ms=lambda: clock[0], push_msg=False) as engine:
        engine.api_interval = 0
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        if point == "after_intent":
            monkeypatch.setattr(engine, "rate_limit", lambda: clock.__setitem__(0, 1012))
            with pytest.raises(CChanException):
                engine.add_trade(record, 102)
            assert db.get_record(record["id"])["open_order_status"] == "created"
            assert engine.sim_state.orders == {}
        else:
            engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
            result = engine.add_trade(record, 102)
            if point == "after_query_check":
                original = engine.paper_inputs.available
                def advance_clock(*args, **kwargs):
                    answer = original(*args, **kwargs)
                    clock[0] = 1012
                    return answer
                monkeypatch.setattr(engine.paper_inputs, "available", advance_clock)
            else:
                original = engine._paper_execution_price
                def advance_clock(*args, **kwargs):
                    answer = original(*args, **kwargs)
                    clock[0] = 1012
                    return answer
                monkeypatch.setattr(engine, "_paper_execution_price", advance_clock)
            before = engine.get_sim_account_report()
            with pytest.raises(CChanException):
                engine.query_order(CODE, result.order_id)
            assert engine.get_sim_account_report() == before


def test_configured_quote_age_policy_cannot_be_widened_after_binding(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, _ = runtime
    clock = [1001]
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: clock[0], push_msg=False) as engine:
        engine.paper_inputs.max_age_ms = 1_000_000
        clock[0] = 1012
        with pytest.raises(CChanException):
            engine.paper_inputs.prices(engine)


def test_explicit_paper_risk_parameters_do_not_read_repository_private_files(runtime, monkeypatch):
    from Trade.Script.OpenConfig import COpenConfig
    _, path, config = runtime
    config["trade"]["open_para"] = {"score_thred": 0.25, "max_sl_rate": 0.05, "bsp_type_filter": "1,2"}
    path.write_bytes(canonical_bytes(config))
    def forbidden(*args):
        raise AssertionError("private/default risk file must not be read")
    monkeypatch.setattr(COpenConfig, "_load", forbidden)
    actual = COpenConfig.configured(CEnv(str(path)))
    assert actual.score_thred == 0.25 and actual.max_sl_rate == 0.05
    assert actual.pass_bsp_type("1") and not actual.pass_bsp_type("3a")


@pytest.mark.parametrize("module", ["RestoreOrders", "ClosePreErrorOpen", "RealTimeTracker", "RetradeCoverOrder"])
def test_real_management_cli_uses_the_original_server_and_returns_a_true_exit_status(runtime, module):
    db, path, config = runtime
    record = db.get_record(db.add_signal(make_signal(code=CODE)))
    with CPersistentPaperState.open(config["trade"]["paper"]["server_path"], database=config["db"]["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
        if module == "RestoreOrders":
            engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
        engine.add_trade(record, 102)
        if module == "ClosePreErrorOpen":
            db.set_open_err(record["id"], "offline fixture requires reduction")
        if module == "RetradeCoverOrder":
            engine.set_sim_quote(CODE, at_ms=1002, bid="99.9", ask="100", mark_price="100")
            engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(record["id"]), "close"), [0.01, 0.03])
            engine.cover_trade(db.get_record(record["id"]), None, "offline partial reduction")
    quote_path = Path(config["trade"]["paper"]["quote_path"])
    doc = publish_quotes(quote_path, 1003)
    if module == "RealTimeTracker":
        doc["payload"]["quotes"][0].update(bid="89.9", ask="90", mark="90", last=89.9)
        doc["payload_sha256"] = hashlib.sha256(canonical_bytes(doc["payload"])).hexdigest()
        quote_path.write_bytes(canonical_bytes(doc))
    result = subprocess.run([sys.executable, "-c", CLI_WORKER, f"Trade.Script.{module}", "1003"],
        cwd=ROOT, env={**os.environ, "CHANPY_CONFIG": str(path)}, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout+result.stderr
    assert db.get_record(record["id"])["current_qty"] == (0.03 if module == "RestoreOrders" else 0)
    with CPersistentPaperState.open(config["trade"]["paper"]["server_path"], database=config["db"]["sqlite_path"]) as server:
        assert len(server.state.orders) == (1 if module == "RestoreOrders" else 2)


def test_software_price_adapter_does_not_claim_an_exchange_timestamp(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, _ = runtime
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1001, push_msg=False) as engine:
        document = engine.paper_inputs.price_batch(engine)
        assert document["schema"] == "chan-software-entry-quotes-v1"
        assert document["payload"]["clock_kind"] == "explicit_software_clock"
        assert document["payload"]["synthetic_only"] is True


def test_library_profile_orders_cannot_lose_the_original_age_policy_on_restart(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, config = runtime
    with configured_trade_engine(db, env=CEnv(str(path)), quota_gen=CBenchPriceQuotaGen(3.7), now_ms=lambda: 1001, push_msg=False) as engine:
        engine.api_interval = 0
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.set_sim_fill_plan(engine.make_client_order_id(record, "open"), [0.01, 0.03])
        result = engine.add_trade(record, 102)
    with CPersistentPaperState.open(config["trade"]["paper"]["server_path"], database=config["db"]["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        assert engine.query_order(CODE, result.order_id).filled == 0.01
        with pytest.raises(CChanException):
            engine.cover_trade(db.get_record(record["id"]), None, "no current software reader")


def test_error_repair_can_reduce_the_remainder_after_a_confirmed_partial_close_cancel(runtime):
    from Trade.Script.TradeRuntime import configured_trade_engine
    from Trade.Script.ClosePreErrorOpen import close_pre_error_open
    db, path, config = runtime
    with configured_trade_engine(db, env=CEnv(str(path)), quota_gen=CBenchPriceQuotaGen(3.7), now_ms=lambda: 1001, push_msg=False) as engine:
        engine.api_interval = 0
        record = db.get_record(db.add_signal(make_signal(code=CODE)))
        engine.add_trade(record, 102)
    publish_quotes(Path(config["trade"]["paper"]["quote_path"]), 1002)
    with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: 1002, push_msg=False) as engine:
        engine.api_interval = 0
        engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(record["id"]), "close"), [0.01, 0.03])
        result = engine.cover_trade(db.get_record(record["id"]), None, "partial exit")
        engine.cancel_order(CODE, result.order_id)
        engine.restore()
        assert db.get_record(record["id"])["cover_order_status"] == "canceled"
        db.set_open_err(record["id"], "still requires original record reduction")
        assert close_pre_error_open(db, engine) == [record["id"]]
        assert db.get_record(record["id"])["current_qty"] == 0
        assert len(engine.sim_state.orders) == 3


def test_post_score_cli_uses_inline_paper_parameters_without_private_file_io(runtime, monkeypatch):
    from Trade.Script import CheckOpenScore as module
    from Trade.Script.OpenConfig import COpenConfig
    _, path, _ = runtime
    monkeypatch.setenv("CHANPY_CONFIG", str(path))
    CEnv.reset_instance()
    def forbidden(*args):
        raise AssertionError("private/default risk file must not be read")
    monkeypatch.setattr(COpenConfig, "_load", forbidden)
    try:
        assert module.main() == 0
    finally:
        CEnv.reset_instance()
