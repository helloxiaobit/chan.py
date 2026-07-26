"""M5 验收测试:ccxt重构(分页/volume/end_date)、ccxt_update增量落库、OfflineDataAPI、SnapshotAPI"""
import os

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.ChanException import CChanException
from Config.EnvConfig import CEnv
from OfflineData.offline_data_util import CKLineDB, import_csv, parse_dt_to_ts

HOUR_MS = 3600 * 1000


class FakeExchange:
    """模拟 ccxt 交易所:确定性K线 + 分页 fetch_ohlcv + fetch_tickers"""

    id = "fake"

    def __init__(self, n=2500, start_ts=1600000000000, step=HOUR_MS):
        self.bars = []
        price = 100.0
        for i in range(n):
            import math
            o = price
            c = 100 + 20 * math.sin(i / 30) + 5 * math.sin(i / 7)
            h, l = max(o, c) + 1, min(o, c) - 1
            self.bars.append([start_ts + i * step, o, h, l, c, 1000.0 + i])
            price = c

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        data = [b for b in self.bars if since is None or b[0] >= since]
        return data[:limit]

    def fetch_tickers(self, code_list):
        last_bar = self.bars[-1]
        return {
            code: {
                "last": last_bar[4], "open": last_bar[1], "high": last_bar[2],
                "low": last_bar[3], "previousClose": last_bar[1], "timestamp": last_bar[0],
            }
            for code in code_list
        }

    @staticmethod
    def parse8601(s):
        from datetime import datetime, timezone
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


@pytest.fixture()
def tmp_env(tmp_path):
    """临时 config.yaml,把离线数据路径指到 tmp 目录"""
    conf_path = tmp_path / "config.yaml"
    conf_path.write_text(
        f"""
db:
  type: sqlite
  sqlite_path: {(tmp_path / 'trade.db').as_posix()}
offline_data:
  root: {tmp_path.as_posix()}
  sqlite_path: {(tmp_path / 'kline.db').as_posix()}
ccxt:
  exchange: binance
""", encoding="utf-8")
    old = os.environ.get("CHANPY_CONFIG")
    os.environ["CHANPY_CONFIG"] = str(conf_path)
    CEnv.reset_instance()
    yield tmp_path
    if old is None:
        os.environ.pop("CHANPY_CONFIG", None)
    else:
        os.environ["CHANPY_CONFIG"] = old
    CEnv.reset_instance()


def test_ccxt_kltype_mapping():
    from DataAPI.ccxt import KLTYPE2TIMEFRAME
    assert KLTYPE2TIMEFRAME[KL_TYPE.K_1M] == "1m"
    assert KLTYPE2TIMEFRAME[KL_TYPE.K_60M] == "1h"
    assert KLTYPE2TIMEFRAME[KL_TYPE.K_MON] == "1M"
    assert KL_TYPE.K_10M not in KLTYPE2TIMEFRAME


def test_ccxt_pagination_and_volume():
    from DataAPI.ccxt import CCXT
    CCXT.exchange = FakeExchange(n=2500)
    try:
        api = CCXT("BTC/USDT", k_type=KL_TYPE.K_60M, begin_date="2020-09-13", end_date=None)
        klus = list(api.get_kl_data())
        assert len(klus) == 2500, "since 分页应拉到全量(2500根,超过单页1000)"
        assert all(klus[i].time < klus[i + 1].time for i in range(len(klus) - 1))
        assert klus[0].trade_info.metric[DATA_FIELD.FIELD_VOLUME] == 1000.0
    finally:
        CCXT.exchange = None


def test_ccxt_end_date():
    from DataAPI.ccxt import CCXT
    fake = FakeExchange(n=100, start_ts=FakeExchange.parse8601("2024-01-01T00:00:00Z"))
    CCXT.exchange = fake
    try:
        api = CCXT("BTC/USDT", k_type=KL_TYPE.K_60M, begin_date="2024-01-01", end_date="2024-01-03")
        klus = list(api.get_kl_data())
        assert len(klus) == 48  # 两天整,end_date 当天不含
    finally:
        CCXT.exchange = None


def test_ccxt_unsupported_lv():
    from DataAPI.ccxt import CCXT
    CCXT.exchange = FakeExchange(n=10)
    try:
        api = CCXT("BTC/USDT", k_type=KL_TYPE.K_10M, begin_date=None, end_date=None)
        with pytest.raises(CChanException):
            list(api.get_kl_data())
    finally:
        CCXT.exchange = None


def test_kline_db(tmp_path):
    with CKLineDB(str(tmp_path / "t.db")) as db:
        rows = [(i * HOUR_MS, 1.0, 2.0, 0.5, 1.5, 10.0) for i in range(10)]
        db.upsert_klines("X/Y", KL_TYPE.K_60M, rows)
        db.upsert_klines("X/Y", KL_TYPE.K_60M, rows[5:])  # 重复upsert不重复计数
        assert db.count("X/Y", KL_TYPE.K_60M) == 10
        assert db.last_ts("X/Y", KL_TYPE.K_60M) == 9 * HOUR_MS
        part = db.query_klines("X/Y", KL_TYPE.K_60M, begin_ts=3 * HOUR_MS, end_ts=7 * HOUR_MS)
        assert [r[0] for r in part] == [3 * HOUR_MS, 4 * HOUR_MS, 5 * HOUR_MS, 6 * HOUR_MS]
        assert ("X/Y", "K_60M") in db.symbols()


def test_ccxt_update_incremental(tmp_path):
    from OfflineData.ccxt_update import update_symbol
    fake = FakeExchange(n=1500)
    with CKLineDB(str(tmp_path / "kline.db")) as db:
        cnt1 = update_symbol("BTC/USDT", KL_TYPE.K_60M, db=db, exchange=fake,
                             begin_time="2020-09-01", verbose=False)
        assert cnt1 == 1500
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 1500
        # 交易所新增500根 → 第二次只增量拉新
        fake2 = FakeExchange(n=2000)
        cnt2 = update_symbol("BTC/USDT", KL_TYPE.K_60M, db=db, exchange=fake2, verbose=False)
        assert cnt2 == 500
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 2000


def test_offline_reader_from_sqlite(tmp_env, synthetic_bars):
    """sqlite 落地数据 → CStockFileReader → 缠论计算跑通"""
    db_path = str(tmp_env / "kline.db")
    with CKLineDB(db_path) as db:
        rows = [
            (parse_dt_to_ts(f"{b['year']:04}-{b['month']:02}-{b['day']:02}"),
             b["open"], b["high"], b["low"], b["close"], b["volume"])
            for b in synthetic_bars
        ]
        db.upsert_klines("TEST/USDT", KL_TYPE.K_DAY, rows)
    chan = CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({"divergence_rate": float("inf"), "min_zs_cnt": 0}),
        autype=AUTYPE.NONE,
    )
    assert len(chan[0].bi_list) > 10
    assert len(chan[0].seg_list) > 2
    last_klu = chan[0][-1][-1]
    assert last_klu.trade_info.metric[DATA_FIELD.FIELD_VOLUME] > 0


def test_offline_reader_csv_fallback(tmp_env, synthetic_bars):
    csv_path = tmp_env / "TEST2_USDT_day.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close,volume\n")
        for b in synthetic_bars[:300]:
            f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}\n")
    chan = CChan(
        code="TEST2/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({}),
        autype=AUTYPE.NONE,
    )
    assert sum(len(klc.lst) for klc in chan[0]) == 300


def test_offline_reader_missing_raises(tmp_env):
    with pytest.raises(CChanException) as e:
        CChan(
            code="NOT/EXIST",
            data_src="custom:OfflineDataAPI.CStockFileReader",
            lv_list=[KL_TYPE.K_DAY],
            config=CChanConfig({}),
            autype=AUTYPE.NONE,
        )
    assert "离线数据不存在" in str(e.value)


def test_import_csv(tmp_path, synthetic_bars):
    csv_path = tmp_path / "import.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close,volume\n")
        for b in synthetic_bars[:100]:
            f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}\n")
    with CKLineDB(str(tmp_path / "kline.db")) as db:
        cnt = import_csv(db, "IMP/TEST", KL_TYPE.K_DAY, str(csv_path))
        assert cnt == 100
        assert db.count("IMP/TEST", KL_TYPE.K_DAY) == 100


def test_ccxt_snapshot_and_price_query():
    from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
    from DataAPI.SnapshotAPI.StockSnapshotAPI import priceQuery
    CCCXTSnapshot.exchange = FakeExchange(n=50)
    try:
        res = priceQuery(["BTC/USDT", "ETH/USDT"], engine="ccxt", return_klu=False)
        assert set(res.keys()) == {"BTC/USDT", "ETH/USDT"}
        for v in res.values():
            assert v is not None and {"price", "high", "low"} <= set(v.keys())
        res_klu = priceQuery(["BTC/USDT"], engine="ccxt", return_klu=True)
        klu = res_klu["BTC/USDT"]
        from KLine.KLine_Unit import CKLine_Unit
        assert isinstance(klu, CKLine_Unit)
        assert klu.low <= klu.close <= klu.high
    finally:
        CCCXTSnapshot.exchange = None


def test_price_query_unknown_engine():
    from DataAPI.SnapshotAPI.StockSnapshotAPI import priceQuery
    with pytest.raises(CChanException):
        priceQuery(["BTC/USDT"], engine="not_exist")


@pytest.mark.network
def test_real_ccxt_update_btc(tmp_path):
    """真实网络:BTC/USDT 1h 增量更新到 sqlite(网络不可用则跳过)"""
    from OfflineData.ccxt_update import update_symbol
    try:
        with CKLineDB(str(tmp_path / "kline.db")) as db:
            cnt = update_symbol("BTC/USDT", KL_TYPE.K_60M, db=db, begin_time="2025-06-01", verbose=False)
            assert cnt > 1000
            assert db.count("BTC/USDT", KL_TYPE.K_60M) == cnt
    except CChanException as e:
        pytest.skip(f"网络不可用,跳过: {e}")
