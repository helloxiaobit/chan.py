"""交易辅助:市场判断/交易时段"""
import datetime
from typing import Optional


def get_market(code: str) -> str:
    from ModelStrategy.ModelGenerator import get_market as _get_market
    return _get_market(code)


def is_market_open(market: str, now: Optional[datetime.datetime] = None) -> bool:
    """粗粒度交易时段判断:crypto 7×24 直通;A股按北京时间工作日 9:30-11:30/13:00-15:00;
    港股 9:30-12:00/13:00-16:00;美股不判断夏令时,默认 21:30-04:00(北京时间)"""
    if market == "crypto":
        return True
    now = now or datetime.datetime.now()
    if market in ("cn", "hk") and now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    if market == "cn":
        return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60)
    if market == "hk":
        return (9 * 60 + 30 <= t <= 12 * 60) or (13 * 60 <= t <= 16 * 60)
    if market == "us":
        return t >= 21 * 60 + 30 or t <= 4 * 60
    return True
