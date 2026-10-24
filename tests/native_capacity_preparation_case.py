"""All-live-mode *fake* history, then original SDK with bottom-only HTTP fake.

No real configuration/environment is changed. Fake dictionaries satisfy the
original safety gates; this is not live/testnet certification or permission.
"""
import copy
import json
from urllib.parse import parse_qs, urlsplit

from requests import Response

from .native_order_preparation_case import native_order_case


PATHS = {
    "/fapi/v3/balance": "fapiPrivateV3GetBalance", "/fapi/v3/account": "fapiPrivateV3GetAccount",
    "/fapi/v3/positionRisk": "fapiPrivateV3GetPositionRisk", "/fapi/v1/accountConfig": "fapiPrivateGetAccountConfig",
    "/fapi/v1/symbolConfig": "fapiPrivateGetSymbolConfig", "/fapi/v1/leverageBracket": "fapiPrivateGetLeverageBracket",
    "/fapi/v1/multiAssetsMargin": "fapiPrivateGetMultiAssetsMargin", "/fapi/v1/positionSide/dual": "fapiPrivateGetPositionSideDual",
    "/fapi/v1/openOrders": "fapiPrivateGetOpenOrders", "/fapi/v1/openAlgoOrders": "fapiPrivateGetOpenAlgoOrders",
    "/fapi/v1/userTrades": "fapiPrivateGetUserTrades", "/fapi/v1/income": "fapiPrivateGetIncome",
    "/fapi/v1/exchangeInfo": "fapiPublicGetExchangeInfo", "/fapi/v1/premiumIndex": "fapiPublicGetPremiumIndex",
    "/fapi/v1/ticker/bookTicker": "fapiPublicGetTickerBookTicker", "/fapi/v1/feeBurn": "fapiPrivateGetFeeBurn",
    "/fapi/v1/commissionRate": "fapiPrivateGetCommissionRate", "/fapi/v1/ticker/24hr": "fapiPublicGetTicker24hr",
}


def native_capacity_prepare_case(db, conf, tmp_path, monkeypatch, *, mode="one_way", side=True):
    case = native_order_case(db, conf, tmp_path, monkeypatch, "binance", mode=mode, side=side, execution_mode="live")
    client = case["client"]
    handlers = {name: getattr(client, name) for name in PATHS.values() if name in client.__dict__}
    for name in (*handlers, "request"):
        if name in client.__dict__:
            monkeypatch.delattr(client, name)
    # Install fake credentials on this isolated SDK only, matching its fake
    # Engine config. Never write os.environ or a user's actual configuration.
    client.apiKey, client.secret, client.enableRateLimit = "key", "secret", False
    calls = []
    def no_http(*args, **kwargs):
        raise AssertionError("only the isolated client's fake session may handle requests")
    monkeypatch.setattr("requests.sessions.Session.request", no_http)
    def transport(method, url, **kwargs):
        parsed = urlsplit(url)
        assert method == "GET" and parsed.hostname == "fapi.binance.com" and parsed.path in PATHS
        assert kwargs["verify"] is True and not db.db.conn.in_transaction
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        params = {key: int(value) if key in {"startTime", "endTime", "limit", "fromId"} else value
                  for key, value in query.items() if key not in {"timestamp", "signature", "recvWindow"}}
        name = PATHS[parsed.path]
        calls.append((name, copy.deepcopy(params)))
        if name == "fapiPrivateGetFeeBurn":
            case["clock"]["now"] += 1
            body = {"feeBurn": False}
        elif name == "fapiPrivateGetCommissionRate":
            case["clock"]["now"] += 1
            body = {"symbol": params["symbol"], "makerCommissionRate": "0.0002", "takerCommissionRate": "0.0004"}
        elif name == "fapiPublicGetTicker24hr":
            case["clock"]["now"] += 1
            body = {"symbol": params["symbol"], "priceChange": "0", "priceChangePercent": "0", "weightedAvgPrice": "100",
                "prevClosePrice": "100", "lastPrice": "100", "lastQty": "1", "openPrice": "100", "highPrice": "101",
                "lowPrice": "99", "volume": "10", "quoteVolume": "1000", "openTime": case["clock"]["now"]-1000,
                "closeTime": case["clock"]["now"], "firstId": 1, "lastId": 1, "count": 1}
        else:
            assert name in handlers, name
            body = handlers[name](params)
        if name == "fapiPrivateGetSymbolConfig":
            body = [{**row, "maxNotionalValue": "10000"} for row in body if not params.get("symbol") or row["symbol"] == params["symbol"]]
        elif name == "fapiPrivateGetLeverageBracket" and params.get("symbol"):
            body = next(row for row in body if row["symbol"] == params["symbol"])
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response
    monkeypatch.setattr(client.session, "request", transport)
    for module in ("Trade.NativePreparedIntent", "Trade.NativeCapacityEvidence", "Trade.NativeAccountLimits"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: case["clock"]["now"])
    return {**case, "http_calls": calls}
