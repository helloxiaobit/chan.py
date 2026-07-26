"""akshare 实时行情快照(A股;可选依赖 pip install akshare;全市场拉一次再过滤)"""
from typing import List

from .CommSnapshot import CCommSnapshot, T_SNAPSHOT_RES


class CAKShareSnapshot(CCommSnapshot):
    @classmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        res: T_SNAPSHOT_RES = {code: None for code in code_list}
        try:
            import akshare as ak  # 懒加载,可选依赖
        except ImportError:
            print("[CAKShareSnapshot] 需要 akshare,请先 pip install akshare")
            return res
        try:
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            print(f"[CAKShareSnapshot] 行情获取失败: {e}")
            return res
        df = df.set_index("代码")
        for code in code_list:
            symbol = code.split(".")[-1]
            if symbol not in df.index:
                continue
            row = df.loc[symbol]
            try:
                res[code] = cls.make_result({
                    "name": str(row["名称"]),
                    "open": float(row["今开"]),
                    "yesterdayClose": float(row["昨收"]),
                    "price": float(row["最新价"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                }, return_klu)
            except (KeyError, ValueError):
                continue
        return res
