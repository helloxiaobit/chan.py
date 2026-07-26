"""新浪实时行情快照(A股;免费接口,需带 Referer)"""
from typing import List

from .CommSnapshot import CCommSnapshot, T_SNAPSHOT_RES


def to_sina_code(code: str) -> str:
    # sz.000001 → sz000001;sh.600000 → sh600000
    return code.replace(".", "").lower()


class CSinaApi(CCommSnapshot):
    URL = "https://hq.sinajs.cn/list={}"

    @classmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        import requests  # 懒加载
        res: T_SNAPSHOT_RES = {code: None for code in code_list}
        try:
            url = cls.URL.format(",".join(to_sina_code(c) for c in code_list))
            rsp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
            rsp.raise_for_status()
        except Exception as e:
            print(f"[CSinaApi] 请求失败: {e}")
            return res
        lines = rsp.text.strip().split("\n")
        for code, line in zip(code_list, lines):
            try:
                data = line.split('"')[1].split(",")
                if len(data) < 6 or float(data[3]) == 0:
                    continue
                res[code] = cls.make_result({
                    "name": data[0],
                    "open": float(data[1]),
                    "yesterdayClose": float(data[2]),
                    "price": float(data[3]),
                    "high": float(data[4]),
                    "low": float(data[5]),
                }, return_klu)
            except (IndexError, ValueError):
                continue
        return res
