"""Explicit software quote observations, never native market/account certification."""
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from OfflineData.offline_data_util import validate_source_identity
from .LinearPaperAccount import _number, _text


def _fail():
    raise CChanException("软件 paper 行情缺失/变化/过期或单位身份不符，禁止新增模拟成交", ErrCode.SNAPSHOT_ERR) from None


class CSoftwarePaperInputs:
    def __init__(self, path, *, source, max_age_ms, now_ms=None):
        if type(max_age_ms) is not int or not 0 < max_age_ms < 2**63:
            _fail()
        self.path = Path(path).resolve()
        self.source = json.loads(canonical_bytes(validate_source_identity(source)))
        if self.source["market_type"] != "swap" or self.source["settle"] != "USDT" or self.source["price_type"] != "contract":
            _fail()
        self.max_age_ms, self.now_ms = max_age_ms, now_ms or utc_now_ms
        self._policy = canonical_bytes({"path": str(self.path), "source": self.source, "max_age_ms": max_age_ms})
        self._raw, self._quotes, self._identity, self._issues = None, None, None, set()

    @property
    def issues(self):
        return sorted(self._issues)

    def _read(self, engine):
        try:
            raw = self.path.read_bytes()
            document = json.loads(raw)
            payload = document["payload"]
            now, at = self.now_ms(), payload["at_ms"]
            paper = engine._paper()
            if (self._policy != canonical_bytes({"path": str(self.path), "source": self.source, "max_age_ms": self.max_age_ms})
                    or canonical_bytes(document) != raw or set(document) != {"schema", "payload", "payload_sha256"}
                    or document["schema"] != "chan-software-paper-quotes-v1"
                    or set(payload) != {"synthetic_only", "source", "at_ms", "quotes"}
                    or payload["synthetic_only"] is not True or payload["source"] != self.source
                    or hashlib.sha256(canonical_bytes(payload)).hexdigest() != document["payload_sha256"]
                    or type(at) is not int or type(now) is not int or not 0 <= at <= now < 2**63
                    or now-at > self.max_age_ms or not isinstance(payload["quotes"], list)
                    or [row["symbol"] for row in payload["quotes"]] != sorted(paper.markets)
                    or any(("binance" if row["exchange"] == "binanceusdm" else row["exchange"]) != self.source["exchange"]
                        for row in paper.markets.values())):
                _fail()
            quotes = {}
            for row in payload["quotes"]:
                if set(row) != {"symbol", "bid", "ask", "mark", "last"}:
                    _fail()
                symbol = row["symbol"]
                bid, ask, mark = (_number(row[k], positive=True) for k in ("bid", "ask", "mark"))
                if (any(type(row[k]) is not str for k in ("bid", "ask", "mark")) or bid > ask
                        or type(row["last"]) not in (int, float) or _number(row["last"], positive=True) <= 0
                        or any(Fraction(value)/Fraction(paper.markets[symbol]["price_tick"]) % 1 for value in (bid, ask))):
                    _fail()
                quotes[symbol] = {"code": symbol, "at_ms": at, "bid": _text(bid), "ask": _text(ask), "mark_price": _text(mark)}
            return raw, payload, quotes, now
        except Exception:
            _fail()

    def prime(self, engine):
        try:
            raw, _, quotes, _ = self._read(engine)
            if self._raw is not None:
                _fail()  # one original observation per script context
            self._raw, self._quotes = raw, quotes
            self._identity = engine._paper().identity_reference
            for code, values in quotes.items():
                engine.set_sim_quote(code, **{key: value for key, value in values.items() if key != "code"})
        except CChanException:
            self._issues.add("software_paper_quote_unavailable")
            raise

    def check(self, engine, code, *, max_age_ms=None):
        try:
            raw, payload, quotes, started = self._read(engine)
            paper = engine._paper()
            if (self._raw is None or raw != self._raw or quotes != self._quotes or code not in quotes
                    or paper.identity_reference != self._identity or any(paper.quotes.get(key) != value for key, value in quotes.items())):
                _fail()
            finished = self.now_ms()
            if max_age_ms is not None and (type(max_age_ms) is not int or not 0 < max_age_ms < 2**63):
                _fail()
            limit = self.max_age_ms if max_age_ms is None else min(self.max_age_ms, max_age_ms)
            if type(finished) is not int or not started <= finished < 2**63 or finished-payload["at_ms"] > limit:
                _fail()
            return payload
        except Exception:
            self._issues.add("software_paper_quote_unavailable")
            _fail()

    def available(self, engine, code, *, max_age_ms=None):
        try:
            self.check(engine, code, max_age_ms=max_age_ms)
            return True
        except CChanException:
            return False

    def prices(self, engine):
        payload = self.check(engine, next(iter(engine._paper().markets)))
        return {row["symbol"]: row["last"] for row in payload["quotes"]}

    def price_batch(self, engine, *, symbols=None):
        from Common.MarketQuote import make_software_quote_batch
        payload = self.check(engine, next(iter(engine._paper().markets)))
        symbols = sorted(engine._paper().markets) if symbols is None else symbols
        if (not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols)
                or any(code not in engine._paper().markets for code in symbols)):
            _fail()
        return make_software_quote_batch([{"symbol": row["symbol"], "price": row["last"], "timestamp_ms": payload["at_ms"]}
            for row in payload["quotes"] if row["symbol"] in symbols], source=self.source, started_ms=payload["at_ms"],
            finished_ms=payload["at_ms"], max_age_ms=self.max_age_ms)
