"""有界 ticker 观察；接收时刻不是交易所时间，也不是账户/订单准入。"""
import hashlib
import json
import math

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from OfflineData.offline_data_util import validate_source_identity


SCHEMA = "chan-market-quotes-v1"


def _fail():
    raise CChanException("报价来源/时钟/完整性无效或已过期，禁止新增风险", ErrCode.SNAPSHOT_ERR) from None


def _clock(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _validate(document):
    result = json.loads(canonical_bytes(document))
    if (not isinstance(result, dict) or set(result) != {"schema", "payload", "payload_sha256"}
            or result["schema"] != SCHEMA):
        _fail()
    payload = result["payload"]
    if (not isinstance(payload, dict) or set(payload) != {"source", "started_ms", "finished_ms", "quotes", "clock_kind"}
            or payload["clock_kind"] != "exchange_ticker_timestamp" or _digest(payload) != result["payload_sha256"]
            or _clock(payload["started_ms"]) > _clock(payload["finished_ms"])):
        _fail()
    validate_source_identity(payload["source"])
    quotes = payload["quotes"]
    if not isinstance(quotes, list) or not quotes:
        _fail()
    symbols = []
    for quote in quotes:
        if (not isinstance(quote, dict) or set(quote) != {"symbol", "price", "timestamp_ms"}
                or not isinstance(quote["symbol"], str) or not quote["symbol"]
                or type(quote["price"]) not in (int, float) or not math.isfinite(quote["price"]) or quote["price"] <= 0
                or _clock(quote["timestamp_ms"]) > payload["finished_ms"]):
            _fail()
        symbols.append(quote["symbol"])
    if symbols != sorted(set(symbols)):
        _fail()
    return result


def make_quote_batch(quotes, *, source, started_ms, finished_ms):
    """Producer whitelist only; callers must still check age at the use boundary."""
    try:
        payload = {"source": source, "started_ms": started_ms, "finished_ms": finished_ms,
            "quotes": sorted(quotes, key=lambda quote: quote["symbol"]), "clock_kind": "exchange_ticker_timestamp"}
        return _validate({"schema": SCHEMA, "payload": payload, "payload_sha256": _digest(payload)})
    except Exception:
        _fail()


def read_quote_batch(document, *, source, symbols, now_ms, max_age_ms):
    """Fresh original evidence, not a trusted ready/passed boolean or refresh."""
    try:
        now_ms, max_age_ms = _clock(now_ms), _clock(max_age_ms)
        if (not max_age_ms or not isinstance(symbols, list) or not symbols
                or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
                or len(symbols) != len(set(symbols))):
            _fail()
        result = _validate(document)
        payload = result["payload"]
        if (payload["source"] != validate_source_identity(source) or payload["finished_ms"] > now_ms
                or [quote["symbol"] for quote in payload["quotes"]] != sorted(symbols)
                or any(not 0 <= now_ms-quote["timestamp_ms"] <= max_age_ms for quote in payload["quotes"])):
            _fail()
        return result
    except Exception:
        _fail()
