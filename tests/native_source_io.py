"""Dependency-free raw GET pagination shared by in-process and cold tests."""
import copy


class NativeSources:
    """Raw private GETs only; create/cancel are intentionally absent."""
    def __init__(self, venue, rows=None, cash=None):
        self.id, self.rows, self.cash, self.requests = venue, rows or [], cash or [], []
        self.endpoints = []
        self.override = None

    def request(self, kind, params):
        self.requests.append((kind, copy.deepcopy(params)))
        if self.override:
            return self.override(kind, params)
        rows = self.rows if kind == "trades" else self.cash
        start = int(params.get("startTime", params.get("begin", 0)))
        end = int(params.get("endTime", params.get("end", 2**63-1)))
        key = "time" if self.id == "binance" else "ts"
        rows = [r for r in rows if start <= int(r[key]) <= end]
        if self.id == "okx":
            rows = sorted(rows, key=lambda r: int(r["billId"]), reverse=True)
            if "after" in params:
                rows = [r for r in rows if int(r["billId"]) < int(params["after"])]
        result = copy.deepcopy(rows[:int(params["limit"])])
        return result if self.id == "binance" else {"code": "0", "data": result, "msg": ""}

    def fapiPrivateGetUserTrades(self, params):
        return self.request("trades", params)

    def fapiPrivateGetIncome(self, params):
        return self.request("funding", params)

    def privateGetTradeFillsHistory(self, params):
        self.endpoints.append("fills-history")
        return self.request("trades", params)

    def privateGetTradeFills(self, params):
        self.endpoints.append("fills")
        return self.request("trades", params)

    def privateGetAccountBillsArchive(self, params):
        self.endpoints.append("bills-archive")
        return self.request("funding", params)


class AccountSourceIO:
    def __init__(self, venue, rows):
        self.venue, self.rows, self.requests = venue, rows, []
        self.override = None

    def wallet(self, params):
        self.requests.append(copy.deepcopy(params))
        if self.override is not None:
            return self.override(params)
        start = int(params.get("startTime", params.get("begin", 0)))
        end = int(params.get("endTime", params.get("end", 2**63-1)))
        clock = "time" if self.venue == "binance" else "ts"
        rows = [r for r in self.rows if start <= int(r[clock]) <= end]
        if self.venue == "okx":
            rows = sorted(rows, key=lambda r: int(r["billId"]), reverse=True)
            if "after" in params:
                rows = [r for r in rows if int(r["billId"]) < int(params["after"])]
        result = copy.deepcopy(rows[:int(params["limit"])])
        return result if self.venue == "binance" else {"code": "0", "data": result}
