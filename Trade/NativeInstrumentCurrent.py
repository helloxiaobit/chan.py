"""Own instrument collection and bind the original Engine's current cache.

No cache refresh, database write, permission wrapper or default order hook.
The original source bytes remain diagnostic evidence with both flags false.
Local file/SDK checks do not prove server authenticity or loaded-runtime trust.
"""
import json
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativeInstrumentEvidence as source


def _fail():
    raise CChanException("原 Engine 当前 instrument/显式窗口不一致；不构成逐单资金或下单准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _original_method(owner, name, expected):
    actual = getattr(owner, name)
    if getattr(actual, "__self__", None) is not owner or getattr(actual, "__func__", None) is not expected:
        _fail()


def collect_native_instruments_for_engine(engine, codes, *, max_age_ms, max_observation_span_ms):
    """Collect once, compare actual cache and explicit local age/span budgets.

    Age ends after the final checks; it starts at source.started_ms, not its
    request-finished or reader/import time. Span is the source's full window.
    A matching inactive instrument remains nonpermission; no trade gate moves.
    """
    try:
        # Lazy import: importing this reader cannot initialize SDK or Config.
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .db_util import CChanDB
        if type(engine) is not CCCXTTradeEngine:
            _fail()
        provided = {"codes": codes, "mode": engine.mode, "max_age_ms": max_age_ms,
                    "max_observation_span_ms": max_observation_span_ms}
        original = canonical_bytes(provided)
        values = json.loads(original)
        for field in ("max_age_ms", "max_observation_span_ms"):
            if type(values[field]) is not int or not 0 <= values[field] < 2**63:
                _fail()
        targets = source._codes(values["codes"])
        exchange, chan = engine.exchange, engine.chan_db
        if type(chan) is not CChanDB or chan.db_type != "sqlite":
            _fail()
        database, connection, table = chan.db, chan.db.conn, chan.table
        if connection.in_transaction:
            _fail()
        reference, ccxt = source._reference(exchange.id, values["mode"])
        venue = "okx" if exchange.id == "okx" else "binance"
        location = canonical_bytes(database.query("PRAGMA database_list"))
        root = Path(__file__).resolve().parents[1]
        paths = (Path(__file__).resolve(), root/"Trade/CCXTTradeEngine.py")
        implementation = [path.read_bytes() for path in paths]
        started = utc_now_ms()

        def view():
            if (engine.exchange is not exchange or engine.chan_db is not chan or chan.db is not database
                    or database.conn is not connection or chan.table != table or chan.db_type != "sqlite"
                    or connection.in_transaction or canonical_bytes(database.query("PRAGMA database_list")) != location
                    or engine.dry_run is not False or engine.market_type != "swap" or engine.mode != values["mode"]
                    or canonical_bytes(provided) != original or [path.read_bytes() for path in paths] != implementation):
                _fail()
            _original_method(engine, "get_exchange", CCCXTTradeEngine.get_exchange)
            _original_method(engine, "_market_contract", CCCXTTradeEngine._market_contract)
            _original_method(exchange, "load_markets", ccxt.Exchange.load_markets)
            _original_method(exchange, "market", reference.market.__func__)
            # Both mappings must already exist: otherwise the original loader
            # performs I/O or set_markets, neither permitted in this boundary.
            if type(exchange.markets) is not dict or not exchange.markets or type(exchange.markets_by_id) is not dict or not exchange.markets_by_id:
                _fail()
            cache = {"markets": exchange.markets, "markets_by_id": exchange.markets_by_id,
                     "symbols": exchange.symbols, "ids": exchange.ids, "options": exchange.options,
                     "precision_mode": exchange.precisionMode}
            frozen = canonical_bytes(cache)
            environment = source._public_environment(exchange, reference, venue, values["mode"])
            observations = []
            for code in targets:
                if code not in exchange.markets:
                    _fail()
                definition, market = engine._market_contract(code)
                if market is not exchange.markets[code] or type(market.get("active")) is not bool:
                    _fail()
                state = source._text(market["info"]["state" if venue == "okx" else "status"])
                observations.append({"market": definition, "active": market["active"], "native_state": state})
            if canonical_bytes(cache) != frozen:
                _fail()
            return canonical_bytes({"cache": cache, "environment": environment,
                                    "sdk": source._sdk(exchange, ccxt), "observations": observations}), observations

        before, expected = view()
        document = source.collect_native_instrument_evidence(exchange, targets, mode=values["mode"])
        source.verify_native_instrument_evidence(document)
        after, _ = view()
        actual = [{key: row[key] for key in ("market", "active", "native_state")} for row in document["payload"]["observations"]]
        if before != after or canonical_bytes(expected) != canonical_bytes(actual):
            _fail()
        payload, finished = document["payload"], utc_now_ms()
        if (type(started) is not int or type(finished) is not int or not 0 <= started <= payload["started_ms"]
                or not payload["finished_ms"] <= finished < 2**63
                or finished-payload["started_ms"] > values["max_age_ms"]
                or payload["finished_ms"]-payload["started_ms"] > values["max_observation_span_ms"]):
            _fail()
        return document
    except Exception:
        _fail()
