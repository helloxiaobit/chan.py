"""市值过滤(A股海量选股用,低优先;可选依赖 akshare)"""
from typing import Dict, List, Optional


def query_marketvalue(code_list: List[str]) -> Dict[str, Optional[float]]:
    """查询总市值(元);失败的 code 值为 None"""
    res: Dict[str, Optional[float]] = {code: None for code in code_list}
    try:
        import akshare as ak  # 懒加载,可选依赖
        df = ak.stock_zh_a_spot_em().set_index("代码")
    except Exception as e:
        print(f"[MarketValueFilter] 市值查询失败: {e}")
        return res
    for code in code_list:
        symbol = code.split(".")[-1]
        if symbol in df.index:
            try:
                res[code] = float(df.loc[symbol]["总市值"])
            except (KeyError, ValueError):
                continue
    return res


def filter_by_market_value(code_list: List[str], min_mv: float = 5e9) -> List[str]:
    """按最小总市值过滤股票池(默认50亿)"""
    mv = query_marketvalue(code_list)
    return [code for code in code_list if mv.get(code) is not None and mv[code] >= min_mv]
