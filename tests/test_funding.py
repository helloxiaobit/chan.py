"""资金费率数据源与策略过滤测试"""
import pytest

from Common.ChanException import CChanException
from DataAPI.FundingRate import CFundingRate


@pytest.fixture()
def funding_csv(tmp_path):
    p = tmp_path / "funding.csv"
    rows = ["symbol,fundingTime,fundingRate,markPrice"]
    # 2024-01-01 起每8小时一期,前9期 +0.0001,后9期 +0.001(高拥挤)
    from datetime import datetime, timedelta, timezone
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(18):
        rate = 0.0001 if i < 9 else 0.001
        rows.append(f"BTCUSDT,{t.isoformat()},{rate},")
        t += timedelta(hours=8)
    p.write_text("\n".join(rows), encoding="utf-8")
    return str(p)


def test_funding_parse_and_query(funding_csv):
    from datetime import datetime, timezone
    fr = CFundingRate(funding_csv)
    assert len(fr.series) == 18
    # 严格早于:首期结算时刻查询返回 None
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    assert fr.query(t0) is None
    assert fr.query(t0 + 1) == pytest.approx(0.0001)
    # 后期高费率段
    t_late = datetime(2024, 1, 6, tzinfo=timezone.utc).timestamp()
    assert fr.query(t_late) == pytest.approx(0.001)
    # 3日均值(9期):跨前后段时为混合值(01-05 窗口=6期0.0001+3期0.001)
    mid = datetime(2024, 1, 5, tzinfo=timezone.utc).timestamp()
    ma = fr.query_mean(mid)
    assert ma == pytest.approx((6 * 0.0001 + 3 * 0.001) / 9)


def test_funding_cache(funding_csv):
    a = CFundingRate.get(funding_csv)
    b = CFundingRate.get(funding_csv)
    assert a is b


def test_funding_bad_file(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("no,header,here\n1,2,3", encoding="utf-8")
    with pytest.raises(CChanException):
        CFundingRate(str(p))


def test_funding_filter_blocks_longs(tmp_path):
    """费率过滤:极低的 funding_long_max 应禁掉全部多单"""
    import os
    from datetime import datetime, timedelta, timezone

    # 覆盖合成数据全期的高费率序列
    p = tmp_path / "always_high.csv"
    rows = ["symbol,fundingTime,fundingRate,markPrice"]
    t = datetime(2023, 12, 1, tzinfo=timezone.utc)
    for _ in range(3 * 400):
        rows.append(f"TESTUSDT,{t.isoformat()},0.001,")
        t += timedelta(hours=8)
    p.write_text("\n".join(rows), encoding="utf-8")

    # 复用多级别合成环境
    from .test_multilv import BASE_CONF, LV_LIST, bars_3lv, gen_15m_bars, aggregate  # noqa: F401
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, KL_TYPE
    from Config.EnvConfig import CEnv
    from OfflineData.offline_data_util import CKLineDB

    conf_path = tmp_path / "config.yaml"
    conf_path.write_text(
        f"offline_data:\n  root: {tmp_path.as_posix()}\n  sqlite_path: {(tmp_path / 'kline.db').as_posix()}\n",
        encoding="utf-8")
    old = os.environ.get("CHANPY_CONFIG")
    os.environ["CHANPY_CONFIG"] = str(conf_path)
    CEnv.reset_instance()
    try:
        b15 = gen_15m_bars()
        with CKLineDB(str(tmp_path / "kline.db")) as db:
            db.upsert_klines("TEST/USDT", KL_TYPE.K_15M, b15)
            db.upsert_klines("TEST/USDT", KL_TYPE.K_60M, aggregate(b15, 4))
            db.upsert_klines("TEST/USDT", KL_TYPE.K_4H, aggregate(b15, 16))

        def run(extra):
            chan = CChan(code="TEST/USDT", data_src="custom:OfflineDataAPI.CStockFileReader",
                         lv_list=LV_LIST,
                         config=CChanConfig({**BASE_CONF, "strategy_para": {
                             "skip_features": True, "require_sub_confirm": False, **extra}}),
                         autype=AUTYPE.NONE)
            return list(chan[1].cbsp_strategy)

        base_trades = run({})
        assert any(t.is_buy for t in base_trades), "基线应有多单"
        filtered = run({"funding_csv": str(p), "funding_long_max": 0.0001})
        assert all(not t.is_buy for t in filtered), "高费率+禁多阈值下不应有多单"
        assert len([t for t in filtered if not t.is_buy]) == len([t for t in base_trades if not t.is_buy]), "空单不受影响"
    finally:
        if old is None:
            os.environ.pop("CHANPY_CONFIG", None)
        else:
            os.environ["CHANPY_CONFIG"] = old
        CEnv.reset_instance()
