"""pytdx 实时行情快照(A股;可选依赖 pip install pytdx)"""
from typing import List

from .CommSnapshot import CCommSnapshot, T_SNAPSHOT_RES

HOSTS = [("119.147.212.81", 7709), ("112.74.214.43", 7709), ("124.71.187.122", 7709)]


class CPytdxSnapshot(CCommSnapshot):
    @classmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        res: T_SNAPSHOT_RES = {code: None for code in code_list}
        try:
            from pytdx.hq import TdxHq_API  # 懒加载,可选依赖
        except ImportError:
            print("[CPytdxSnapshot] 需要 pytdx,请先 pip install pytdx")
            return res
        api = TdxHq_API()
        for host, port in HOSTS:
            if api.connect(host, port):
                break
        else:
            print("[CPytdxSnapshot] 所有行情服务器连接失败")
            return res
        try:
            # pytdx market: 0-深圳 1-上海
            query_list = [(0 if c.startswith("sz.") else 1, c.split(".")[-1]) for c in code_list]
            quotes = api.get_security_quotes(query_list) or []
            quote_map = {q["code"]: q for q in quotes}
            for code in code_list:
                q = quote_map.get(code.split(".")[-1])
                if q is None or not q.get("price"):
                    continue
                res[code] = cls.make_result({
                    "name": code,
                    "open": float(q["open"]),
                    "yesterdayClose": float(q["last_close"]),
                    "price": float(q["price"]),
                    "high": float(q["high"]),
                    "low": float(q["low"]),
                }, return_klu)
        finally:
            api.disconnect()
        return res
