"""Two actual modelled markets share one original software account, not two matchers."""
import hashlib
import json
import shutil
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

import pytest

from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.LinearPaperAccount import CLinearPaperAccount, verify_linear_paper_report
from Trade.PaperState import CPersistentPaperState
from Trade.Script.Deployment import CDeployment, publish_deployment
from Trade.Script.RunTradeCycle import run_trade_cycle
from Trade.Script.TradeRuntime import configured_trade_engine
from Trade.db_util import CChanDB
from .test_configured_paper_runtime import publish_quotes
from .test_configured_paper_workflow import actual_dispatch
from .test_deployment_workflow import CODE, SOURCE, deployment_model_data, future_candidates
from .test_linear_paper_account import paper_account, paper_market
from .test_linear_paper_engine import paper_engine

OTHER = "ALT/USDT:USDT"
CODES = (CODE, OTHER)


@pytest.fixture(scope="module", params=["binance", "okx"])
def pool_model(request, tmp_path_factory):
    root = tmp_path_factory.mktemp("portfolio-"+request.param)
    with deployment_model_data(root, source={**SOURCE, "exchange": request.param}, codes=CODES) as model:
        yield model


def write_quotes(path, at, source, quotes):
    document = publish_quotes(path, at)
    document["payload"].update(source=source, quotes=sorted(quotes, key=lambda row: row["symbol"]))
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    path.write_bytes(canonical_bytes(document))


@pytest.fixture(params=["one_way", "hedged"])
def portfolio(pool_model, request, tmp_path, monkeypatch):
    venue = pool_model["source_identity"]["exchange"]
    original_model = Path(pool_model["model"].GetModelPath())
    shutil.copytree(original_model.parent, tmp_path/"models")
    manifest = tmp_path/"deployment.json"
    publish_deployment(manifest, tmp_path/"models"/original_model.name,
                       candidate_score=0, entry_score=0, post_score=0)
    deployment = CDeployment(manifest)
    assert deployment.code_list == sorted(CODES)  # deployment scope is canonically sorted
    request.node.user_properties.extend([
        ("venue", venue), ("position_mode", request.param),
        ("model_artifact_id", deployment.model.artifact_id), ("code_pool", ",".join(CODES)),
    ])
    candidates = future_candidates(pool_model, codes=CODES)
    boundaries = {signal.sig_klu.close_ms for _, signal in candidates.values()}
    assert len(boundaries) == 1
    now = boundaries.pop()+900_000
    markets = {CODE: paper_market(venue), OTHER: {**paper_market(venue), "symbol": OTHER, "base": "ALT",
        "id": "ALTUSDT" if venue == "binance" else "ALT-USDT-SWAP", "contractSize": "0.1", "price_tick": "0.01"}}
    prices, quotes = {}, []
    for code, (chan, signal) in candidates.items():
        deployment.prepare_signal(chan, signal, observed_ms=now)
        chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
        tick = Decimal(markets[code]["price_tick"])
        price = (Decimal(str(signal.open_thred))*Decimal("1.001" if signal.is_buy else "0.999")/tick).to_integral_value(
            rounding=ROUND_CEILING if signal.is_buy else ROUND_FLOOR)*tick
        prices[code] = price
        bid, ask = (price-tick, price) if signal.is_buy else (price, price+tick)
        quotes.append({"symbol": code, "bid": str(bid), "ask": str(ask), "mark": str(price), "last": float(price)})
    assert prices[CODE] != prices[OTHER]
    config = {"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
        "offline_data": {"sqlite_path": str(pool_model["root"]/"kline.db"), "source_identity": deployment.source_identity},
        "ccxt": {"mode": "dry_run", "default_type": "swap", "exchange": venue},
        "snapshot_engine": "sina", "notify": {"backend": "none"},
        "trade": {"deployment_manifest": str(manifest), "bench_price": 100.0, "quote_max_age_ms": 1000,
            "open_para": {}, "paper": {"server_path": str(tmp_path/"server.json"),
                "quote_path": str(tmp_path/"quotes.json"), "quote_max_age_ms": 1000}}}
    path = tmp_path/"runtime.json"
    path.write_bytes(canonical_bytes(config))
    db = CChanDB(db_conf=config["db"])
    keys = {code: db.add_signal(signal) for code, (_, signal) in candidates.items()}
    quantities = {code: (Decimal("100")/prices[code]/Decimal(markets[code]["contractSize"])).to_integral_value(
        rounding=ROUND_FLOOR)*Decimal(markets[code]["contractSize"]) for code in CODES}
    account = CLinearPaperAccount(paper_account().config, markets=list(markets.values()),
        position_mode=request.param, start_ms=1000, identity_seed="portfolio-"+venue+"-"+request.param)
    with CPersistentPaperState.create(tmp_path/"server.json", account=account, database=config["db"]["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        for code in CODES:
            first = Decimal(markets[code]["contractSize"])
            assert quantities[code] > first
            engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(keys[code]), "open"),
                                     [float(first), float(quantities[code])])
    write_quotes(tmp_path/"quotes.json", now, deployment.source_identity, quotes)
    monkeypatch.setenv("CHANPY_CONFIG", str(path))
    CEnv.reset_instance()
    try:
        yield {"db": db, "path": path, "root": tmp_path, "keys": keys, "now": now, "prices": prices,
               "quantities": quantities, "markets": markets, "source": deployment.source_identity,
               "quotes": quotes, "mode": request.param, "venue": venue}
    finally:
        db.close()
        CEnv.reset_instance()


def run_cycle(portfolio, label, at):
    trace = []
    result = run_trade_cycle(portfolio["path"], report_path=portfolio["root"]/(label+".jsonl"),
                            command=actual_dispatch(at, trace), now_ms=lambda: at)
    return result, trace


def report(portfolio, *, previous=None, order_count):
    with CPersistentPaperState.open(portfolio["root"]/"server.json", database=portfolio["root"]/"trade.db") as server:
        value = server.state.paper_account.to_dict()
        assert canonical_bytes(verify_linear_paper_report(value)) == canonical_bytes(value)
        assert len(server.state.orders) == order_count
        assert value["identity"]["position_mode"] == portfolio["mode"]
        assert {market["exchange"] for market in value["identity"]["markets"]} == {portfolio["venue"]}
    if previous is not None:
        assert canonical_bytes(previous["effects"]) == canonical_bytes(value["effects"][:len(previous["effects"])])
    for key in portfolio["keys"].values():
        assert not portfolio["db"].get_order_history(key)["gaps"]
    return value


def test_two_market_default_cycles_recover_fund_and_reduce_only_the_original_lots(portfolio):
    db, keys, now = portfolio["db"], portfolio["keys"], portfolio["now"]
    first, trace = run_cycle(portfolio, "partial", now)
    assert first["status"] == "completed", (first, trace)
    for code, key in keys.items():
        row = db.get_record(key)
        assert row["open_attempt"] == 1
        assert Decimal(str(row["current_qty"])) == Decimal(portfolio["markets"][code]["contractSize"])
        contract = json.loads(row["open_order_contract"])
        market = portfolio["markets"][code]
        assert contract["market"] == {
            **{key: market[key] for key in ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")},
            "precision_mode": "paper_tick_size_v1",
            "precision": {"amount": market["amount_step"], "price": market["price_tick"]},
            "limits": {"amount": {"min": market["amount_step"]}, "price": {"min": market["price_tick"]},
                       "cost": {"min": market["min_notional"]}},
        }
        assert Decimal(contract["quantity"]) == portfolio["quantities"][code]
        assert Decimal(contract["exchange_amount"]) == portfolio["quantities"][code]/Decimal(contract["market"]["contractSize"])
        assert json.loads(row["snapshot_before"])["opening_inputs"]["schema"] == "chan-opening-input-check-v2"
    partial = report(portfolio, order_count=2)
    repeated, trace = run_cycle(portfolio, "restart", now)
    assert repeated["status"] == "completed", (repeated, trace)
    for code, key in keys.items():
        assert db.get_record(key)["open_attempt"] == 1
        assert Decimal(str(db.get_record(key)["current_qty"])) == portfolio["quantities"][code]
    complete = report(portfolio, previous=partial, order_count=2)
    write_quotes(portfolio["root"]/"quotes.json", now+10, portfolio["source"], portfolio["quotes"])
    rates = {CODE: "0.001", OTHER: "-0.002"}
    def apply_funding():
        with configured_trade_engine(db, env=CEnv(str(portfolio["path"])), now_ms=lambda: now+10, push_msg=False) as engine:
            for code in CODES:
                effect = engine.apply_sim_funding(code, at_ms=now+10, rate=rates[code],
                    mark_price=str(portfolio["prices"][code]), event_id="fixed-source-"+code)
                sign = Decimal(1 if db.get_record(keys[code])["is_buy"] else -1)
                expected = -sign*portfolio["quantities"][code]*Decimal(rates[code])*portfolio["prices"][code]
                assert Decimal(effect["cashflow"]["funding_delta"]) == expected
    apply_funding()
    funded = report(portfolio, previous=complete, order_count=2)
    apply_funding()  # new engine/store lifetime, same explicit source events
    assert canonical_bytes(report(portfolio, order_count=2)) == canonical_bytes(funded)
    assert len([effect for effect in funded["effects"] if effect["request"]["kind"] == "funding"]) == 2
    other_row = db.get_record(keys[OTHER])
    other_positions = {key: value for key, value in funded["account"]["snapshot"]["positions"].items() if value["symbol"] == OTHER}
    with configured_trade_engine(db, env=CEnv(str(portfolio["path"])), now_ms=lambda: now+10, push_msg=False) as engine:
        engine.api_interval = 0
        engine.cover_trade(db.get_record(keys[CODE]), None, "explicit original first-market reduction")
    reduced = report(portfolio, previous=funded, order_count=3)
    assert db.get_record(keys[CODE])["current_qty"] == 0
    assert db.get_record(keys[OTHER]) == other_row
    assert {key: value for key, value in reduced["account"]["snapshot"]["positions"].items() if value["symbol"] == OTHER} == other_positions
    manifest = json.loads((portfolio["root"]/"deployment.json").read_bytes())
    model_path = (portfolio["root"]/manifest["model_path"]).resolve()
    model_path.write_bytes(model_path.read_bytes()+b"broken-portfolio-model")
    failed, trace = run_cycle(portfolio, "manage-after-model-failure", now+10)
    assert failed["status"] == "failed" and failed["failed_stage"] == "scope", (failed, trace)
    assert "Trade.Script.MakeOpenTrade" not in [module for module, _, _ in trace]
    assert all(db.get_record(key)["current_qty"] == 0 and db.get_record(key)["open_attempt"] == 1 for key in keys.values())
    final = report(portfolio, previous=reduced, order_count=4)
    assert final["account"]["snapshot"]["positions"] == {}
    assert Decimal(final["account"]["snapshot"]["fees"]) > 0


@pytest.mark.parametrize("damage", ["missing_market", "duplicate_market"])
def test_incomplete_or_duplicate_quote_batch_cannot_partially_admit_the_portfolio(portfolio, damage):
    before = report(portfolio, order_count=0)
    quotes = [row for row in portfolio["quotes"] if row["symbol"] != OTHER]
    if damage == "duplicate_market":
        quotes.append(dict(quotes[0]))
    write_quotes(portfolio["root"]/"quotes.json", portfolio["now"], portfolio["source"], quotes)
    result, trace = run_cycle(portfolio, damage, portfolio["now"])
    assert result["status"] == "failed", (result, trace)
    assert "Trade.Script.MakeOpenTrade" not in [module for module, _, _ in trace]
    assert all(portfolio["db"].get_record(key)["open_attempt"] == 0 for key in portfolio["keys"].values())
    assert canonical_bytes(report(portfolio, order_count=0)) == canonical_bytes(before)
