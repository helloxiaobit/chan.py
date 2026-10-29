"""Cold original CLI processes; only synthetic raw HTTP lives in this helper.

The parent seeds the original mixed SQLite history once. Children never build
fixtures, call an Engine substitute, mint admission evidence, or reseed a DB.
"""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import runpy
import socket
import sys
from urllib.parse import parse_qs, urlsplit

import requests


def export_raw_venue(case, path):
    """Export raw fake responses, not a second account or an admission receipt."""
    from .native_capacity_preparation_case import PATHS
    symbols = [unit["id"] for unit in case["units"]]
    client, static, per_symbol = case["client"], {}, {}
    symbol_paths = {"/fapi/v1/premiumIndex", "/fapi/v1/ticker/bookTicker", "/fapi/v1/commissionRate"}
    for endpoint, name in PATHS.items():
        if endpoint in {"/fapi/v1/userTrades", "/fapi/v1/income"}:
            continue
        if endpoint in symbol_paths:
            per_symbol[endpoint] = {symbol: getattr(client, name)({"symbol": symbol}) for symbol in symbols}
        else:
            static[endpoint] = getattr(client, name)({})
    data = {"schema": "test-only-native-raw-venue", "now_ms": case["clock"]["now"],
        "static": static, "per_symbol": per_symbol, "pending": case["pending_raw"], "submitted": None,
        "executions": {symbol: {"trades": source.rows, "funding": source.cash}
                       for symbol, source in case["execution_io"].items()}, "wallet": case["wallet_io"].rows}
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def _run(path, trace_path, module):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["schema"] == "test-only-native-raw-venue"
    clock = {"now": data["now_ms"]}

    def trace(**item):
        with Path(trace_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), **item})+"\n")

    def blocked(*args, **kwargs):
        trace(kind="network_escape_blocked")
        raise AssertionError("native process fixture forbids all socket connections")

    # Requests/ssl are imported first, so blocking cannot break SSL class setup.
    socket.create_connection = socket.socket.connect = socket.socket.connect_ex = blocked
    from Common import KLineTime
    KLineTime.utc_now_ms = lambda: clock["now"]
    from Trade import NativePreparedClient, NativePreparedIntent, NativeLastPrice
    for module_clock in (NativePreparedClient, NativePreparedIntent, NativeLastPrice):
        module_clock._monotonic_ns = lambda: clock["now"]*1_000_000
    from .native_source_io import NativeSources, AccountSourceIO
    from .test_native_pending_orders import regular_row
    sources = {symbol: NativeSources("binance", rows["trades"], rows["funding"])
               for symbol, rows in data["executions"].items()}
    wallet = AccountSourceIO("binance", data["wallet"])

    def transport(session, method, url, **kwargs):
        target = urlsplit(url)
        assert kwargs["verify"] is True
        params = {key: values[0] for key, values in parse_qs(target.query).items()
                  if key not in {"timestamp", "signature", "recvWindow"}}
        body = kwargs.get("data") or ""
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        params.update({key: values[0] for key, values in parse_qs(body).items()
                       if key not in {"timestamp", "signature", "recvWindow"}})
        trace(kind="http", method=method, host=target.hostname, path=target.path, params=params)
        clock["now"] += 1
        assert method in {"GET", "POST"}
        if method == "POST":
            assert (target.hostname, target.path) == ("fapi.binance.com", "/fapi/v1/order")
            assert data["submitted"] is None, "a second actual SDK submission is forbidden"
            row = regular_row("binance", params["symbol"], 123456)
            row.update(clientOrderId=params["newClientOrderId"], origQty=params["quantity"], price=params["price"],
                side=params["side"], positionSide=params["positionSide"], type=params["type"], origType=params["type"],
                timeInForce=params["timeInForce"], time=clock["now"], updateTime=clock["now"])
            data["submitted"] = row
            Path(path).write_text(json.dumps(data), encoding="utf-8")
            body = row
        elif target.hostname == "api.binance.com" and target.path in {
                "/sapi/v1/capital/config/getall", "/sapi/v1/margin/allPairs", "/sapi/v1/margin/isolated/allPairs"}:
            body = []
        elif (target.hostname, target.path) in {("api.binance.com", "/api/v3/exchangeInfo"),
                                              ("dapi.binance.com", "/dapi/v1/exchangeInfo")}:
            body = {"timezone": "UTC", "serverTime": clock["now"], "symbols": []}
        else:
            assert target.hostname == "fapi.binance.com", "unexpected native host"
            if target.path == "/fapi/v1/order":
                rows = [row for row in (data["pending"], data["submitted"]) if row is not None]
                selected = [row for row in rows if row["symbol"] == params["symbol"] and
                    (str(row["orderId"]) == params.get("orderId") or row["clientOrderId"] == params.get("origClientOrderId"))]
                assert len(selected) == 1, "unknown native order"
                body = copy.deepcopy(selected[0])
                if data.get("query_unavailable") and body["orderId"] == 123456:
                    raise requests.exceptions.Timeout("synthetic native query unavailable")
                body["cumQuote"] = str(Decimal(body["executedQty"])*Decimal(body["avgPrice"]))
            elif target.path == "/fapi/v1/openOrders":
                body = [copy.deepcopy(row) for row in (data["pending"], data["submitted"]) if row is not None and
                    row["status"] in {"NEW", "PARTIALLY_FILLED"} and (not params.get("symbol") or row["symbol"] == params["symbol"])]
            elif target.path == "/fapi/v1/userTrades":
                body = sources[params["symbol"]].request("trades", params)
            elif target.path == "/fapi/v1/income":
                body = (sources[params["symbol"]].request("funding", params) if params.get("incomeType") == "FUNDING_FEE"
                        else wallet.wallet(params))
            elif target.path == "/fapi/v2/ticker/price":
                body = {"symbol": params["symbol"], "price": "102.12345678901234567890123456789", "time": clock["now"]}
            elif target.path in data["per_symbol"]:
                body = copy.deepcopy(data["per_symbol"][target.path][params["symbol"]])
                if "time" in body:
                    body["time"] = clock["now"]
            else:
                assert target.path in data["static"], "unexpected native path"
                body = copy.deepcopy(data["static"][target.path])
                if target.path == "/fapi/v1/symbolConfig" and params.get("symbol"):
                    body = [row for row in body if row["symbol"] == params["symbol"]]
                elif target.path == "/fapi/v1/leverageBracket" and params.get("symbol"):
                    body = next(row for row in body if row["symbol"] == params["symbol"])
        response = requests.Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response

    requests.sessions.Session.request = transport
    trace(kind="boot", module=module, preloaded=module in sys.modules,
          database=json.loads(Path(os.environ["CHANPY_CONFIG"]).read_bytes())["db"]["sqlite_path"])
    sys.argv = ["Trade.Script.RunTradeStage", module]
    # Imports of the original stage/CLI happen only after the fake clock and I/O.
    try:
        runpy.run_module("Trade.Script.RunTradeStage", run_name="__main__")
    finally:
        data["now_ms"] = clock["now"]
        Path(path).write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    _run(*sys.argv[1:])
