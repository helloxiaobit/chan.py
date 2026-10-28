"""Configured native CLI keeps original SDK/CAS; only bottom I/O is fake."""
import copy
import json
from urllib.parse import urlsplit

import pytest
from requests import Response

from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
from OfflineData.offline_data_util import CKLineDB
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.Script import MakeOpenTrade
from Trade.Script.OpeningInputs import COpeningInputs
from Trade.Script.RunTradeCycle import run_trade_cycle
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_monetary_default_entry import install_profile
from .test_native_monetary_execution import install_order_transport
from .test_native_prepared_last import install_last
from .test_trade_cycle import cycle, command_log, run, MANAGEMENT


def freeze_cli_epoch(case, monkeypatch):
    monkeypatch.setattr(CEnv, "_instance", CEnv(str(case["config"])))
    expected = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"]).snapshot()
    for key, value in expected.items():
        monkeypatch.setenv("CHANPY_CYCLE_"+key.upper(), value)


def configure_cli(case, monkeypatch):
    """Only this temporary fake config/environment, never user settings."""
    install_profile(case)
    config = json.loads(case["config"].read_bytes())
    config["snapshot_engine"] = "ccxt"
    config["ccxt"]["rate_limit"] = False
    price = 101 if case["db"].get_record(case["key"])["is_buy"] else 99
    config["trade"].update(bench_price=price/10, quote_max_age_ms=60000, open_para={},
        strategy_id="approved-strategy", strategy_spec_hash="a"*64)
    case["config"].write_bytes(canonical_bytes(config))
    monkeypatch.setenv("CHANPY_CONFIG", str(case["config"]))
    monkeypatch.setenv("CHANPY_CYCLE_ID", "a"*32)
    monkeypatch.setenv("CHANPY_LIVE_TRADING_UNLOCK", "I_ACCEPT_REAL_ORDERS")
    monkeypatch.delenv("CHANPY_KILL_SWITCH", raising=False)
    monkeypatch.setattr(MakeOpenTrade, "utc_now_ms", lambda: case["clock"]["now"])
    freeze_cli_epoch(case, monkeypatch)
    install_last(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    previous, quote_calls = case["client"].session.request, []

    def transport(method, url, **kwargs):
        if method != "GET" or urlsplit(url).path != "/fapi/v1/ticker/24hr":
            return previous(method, url, **kwargs)
        assert urlsplit(url).hostname == "fapi.binance.com" and kwargs["verify"] is True
        assert not case["db"].db.conn.in_transaction
        quote_calls.append(url)
        rows = [{"symbol": unit["id"], "lastPrice": str(price), "bidPrice": str(price-.1), "askPrice": str(price+.1),
            "openTime": case["clock"]["now"]-1000, "closeTime": case["clock"]["now"],
            "openPrice": "100", "highPrice": "102", "lowPrice": "98", "volume": "10", "quoteVolume": str(price*10)}
            for unit in case["units"]]
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(rows).encode()
        return response

    monkeypatch.setattr(case["client"].session, "request", transport)
    # The actual cold engine still uses the original factory, SDK and methods.
    # Every session is confined to this preinstalled fake transport.
    monkeypatch.setattr("requests.sessions.Session.request", lambda session, method, url, **kw: transport(method, url, **kw))
    monkeypatch.setattr(CCCXTSnapshot, "exchange", case["client"])
    return posts, quote_calls


def test_original_configured_cli_reaches_one_owned_native_claim_and_post(capacity_case, monkeypatch, capsys):
    case = capacity_case
    posts, quote_calls = configure_cli(case, monkeypatch)
    previous = copy.deepcopy(case["db"].get_record(case["key"]))
    result = MakeOpenTrade.main()
    assert result == 0, "the configured CLI still blocks the already-integrated native monetary path"
    assert len(posts) == 1 and len(quote_calls) == 1
    record = case["db"].get_record(case["key"])
    assert previous["open_attempt"] == 0 and record["open_attempt"] == 1
    assert record["open_order_status"] == "open" and record["open_order_id"] == "123456"
    document = read_native_order_transition(case["db"], case["key"])
    binding = document["payload"]["root"]["preparation"]
    assert document["payload"]["stage"] == "claim" and binding["schema"] == "chan-native-prepared-intent-binding-v4"
    assert binding["monetary"]["payload"]["status"] == "within_model_capacity"
    snapshot = json.loads(record["snapshot_before"])
    assert snapshot["opening_inputs"]["quote"]["batch"]["payload"]["quotes"][0]["price"] == (101 if previous["is_buy"] else 99)
    assert snapshot["opening_inputs"]["native_admission_verified"] is False
    assert posts[0]["side"] == ("BUY" if previous["is_buy"] else "SELL")
    assert posts[0]["positionSide"] == record["position_side"]
    assert posts[0]["price"] == str(101 if previous["is_buy"] else 99)
    events = case["db"].get_order_history(case["key"])["attempts"][0]["events"]
    assert [event["kind"] for event in events][:4] == ["intent", "claim", "ack", "sdk_submission_report"]
    assert MakeOpenTrade.main() == 0 and len(posts) == 1 and len(quote_calls) == 1
    output = capsys.readouterr()
    assert "I_ACCEPT_REAL_ORDERS" not in output.out+output.err


@pytest.mark.parametrize("missing", ["profile", "before", "budget", "candidate", "unlock", "kill", "notional", "partial_profile", "bool_notional"])
def test_original_cli_refuses_configuration_or_permission_gaps_before_quotes(single_case, monkeypatch, missing):
    case = single_case
    posts, quote_calls = configure_cli(case, monkeypatch)
    config = json.loads(case["config"].read_bytes())
    if missing == "profile":
        del config["trade"]["native_admission"]
    elif missing == "before":
        config["trade"]["native_admission"]["before_id"] = "0"*64
    elif missing == "budget":
        del config["trade"]["native_admission"]["last_max_age_ms"]
    elif missing == "candidate":
        config["trade"]["strategy_receipt"] = ""
    elif missing == "unlock":
        monkeypatch.delenv("CHANPY_LIVE_TRADING_UNLOCK")
    elif missing == "kill":
        monkeypatch.setenv("CHANPY_KILL_SWITCH", "YES")
    elif missing == "notional":
        del config["trade"]["bench_price"]
    elif missing == "partial_profile":
        config["trade"]["native_admission"] = {"schema": "chan-native-entry-profile-v1"}
    else:
        config["trade"]["bench_price"] = True
    case["config"].write_bytes(canonical_bytes(config))
    freeze_cli_epoch(case, monkeypatch)
    original = canonical_bytes([case["db"].query_all(),
        [case["db"].get_order_history(key) for key in [*case["history_keys"], case["key"]]]])
    before_calls = list(case["http_calls"])
    assert MakeOpenTrade.main() == 1
    assert posts == [] and quote_calls == [], "invalid native configuration must be refused before quotes or prepare"
    assert case["http_calls"] == before_calls
    assert canonical_bytes([case["db"].query_all(),
        [case["db"].get_order_history(key) for key in [*case["history_keys"], case["key"]]]]) == original


def test_cycle_routes_declared_native_profile_without_claiming_admission(cycle):
    import yaml
    cycle[2]["ccxt"]["mode"] = "testnet"
    # Routing declaration only, deliberately no source/permission proof. The
    # real child/Engine must still reject an incomplete profile independently.
    cycle[2]["trade"]["native_admission"] = {"schema": "chan-native-entry-profile-v1"}
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    calls, command = command_log()
    result = run(cycle, command)
    assert "Trade.Script.MakeOpenTrade" in [row[0] for row in calls], "cycle still has its old integration placeholder"
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["status"] == "completed" and result["native_admission_verified"] is False


def test_cycle_native_child_failure_still_runs_original_management(cycle):
    import yaml
    cycle[2]["ccxt"]["mode"] = "testnet"
    cycle[2]["trade"]["native_admission"] = {"schema": "chan-native-entry-profile-v1"}
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    calls, command = command_log(fail="Trade.Script.MakeOpenTrade")
    result = run(cycle, command)
    assert [row[0] for row in calls].count("Trade.Script.MakeOpenTrade") == 1
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["status"] == "failed" and result["exit_code"] == 37
    assert result["native_admission_verified"] is False


def test_cycle_passes_its_own_input_epoch_to_the_actual_native_cli(single_case, monkeypatch, tmp_path):
    case = single_case
    posts, quote_calls = configure_cli(case, monkeypatch)
    calls, open_epochs = [], []
    def command(module, args, *, cwd, env):
        calls.append(module)
        if module != "Trade.Script.MakeOpenTrade":
            return 0  # Existing closed fixture data; no external stage I/O.
        open_epochs.append({key: value for key, value in env.items() if key.startswith("CHANPY_CYCLE_")})
        with monkeypatch.context() as child:
            for key, value in env.items():
                child.setenv(key, value)
            return MakeOpenTrade.main()
    result = run_trade_cycle(case["config"], report_path=tmp_path/"native-cycle.jsonl",
        command=command, now_ms=lambda: case["clock"]["now"])
    assert result["status"] == "completed" and result["native_admission_verified"] is False
    assert calls.count("Trade.Script.MakeOpenTrade") == 1 and calls[-4:] == MANAGEMENT
    assert len(posts) == len(quote_calls) == len(open_epochs) == 1
    assert open_epochs[0]["CHANPY_CYCLE_ID"] == result["run_id"] != "a"*32
    expected = result["opening_inputs"]
    assert all(open_epochs[0]["CHANPY_CYCLE_"+key.upper()] == value for key, value in expected.items())
    snapshot = json.loads(case["db"].get_record(case["key"])["snapshot_before"])["opening_inputs"]
    assert all(snapshot[key] == value for key, value in expected.items())
    assert read_native_order_transition(case["db"], case["key"])["payload"]["stage"] == "claim"


@pytest.mark.parametrize("damage", ["cycle_id", "epoch", "bars", "stale_quote"])
def test_native_cli_epoch_or_quotes_failure_never_creates_an_intent(single_case, monkeypatch, damage):
    case = single_case
    posts, quote_calls = configure_cli(case, monkeypatch)
    original = canonical_bytes(case["db"].query_all())
    if damage == "cycle_id":
        monkeypatch.delenv("CHANPY_CYCLE_ID")
    elif damage == "epoch":
        monkeypatch.setenv("CHANPY_CYCLE_INPUTS_SHA256", "0"*64)
    elif damage == "bars":
        with CKLineDB(str(case["market_path"])) as market:
            market.conn.execute("UPDATE kline SET v=7 WHERE symbol='ALT/USDT:USDT'")
            market.conn.commit()
    else:
        request = case["client"].session.request
        def stale(method, url, **kwargs):
            response = request(method, url, **kwargs)
            if urlsplit(url).path == "/fapi/v1/ticker/24hr":
                rows = json.loads(response.text)
                for row in rows:
                    row["closeTime"] -= 60001
                response._content = json.dumps(rows).encode()
            return response
        monkeypatch.setattr(case["client"].session, "request", stale)
    assert MakeOpenTrade.main() == 1
    assert posts == [] and canonical_bytes(case["db"].query_all()) == original
    assert len(quote_calls) == (1 if damage == "stale_quote" else 0)
