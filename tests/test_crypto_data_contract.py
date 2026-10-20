"""币圈行情必须以 UTC 收盘边界发布，测试不联网、不读研究资产。"""
from datetime import datetime, timezone

import pytest

from Common.CEnum import AUTYPE, KL_TYPE
from DataAPI.OfflineDataAPI import CStockFileReader
from DataAPI.ccxt import CCXT
from Common.ChanException import CChanException
from OfflineData.offline_data_util import CKLineDB

SOURCE = {"exchange": "binance", "market_type": "spot", "settle": "", "price_type": "contract"}


def ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def bar(open_ms, close=100):
    return [open_ms, 100, 110, 90, close, 1]


@pytest.mark.parametrize("lv,start,end", [
    (KL_TYPE.K_15M, "2024-01-01T23:45", "2024-01-02T00:00"),
    (KL_TYPE.K_60M, "2024-01-01T00:00", "2024-01-01T01:00"),
    (KL_TYPE.K_4H, "2024-01-01T20:00", "2024-01-02T00:00"),
    (KL_TYPE.K_DAY, "2024-01-01T00:00", "2024-01-02T00:00"),
    (KL_TYPE.K_WEEK, "2024-01-01T00:00", "2024-01-08T00:00"),
    (KL_TYPE.K_MON, "2024-02-01T00:00", "2024-03-01T00:00"),
    (KL_TYPE.K_MON, "2024-12-01T00:00", "2025-01-01T00:00"),
])
def test_online_and_offline_publish_the_same_closed_bar(lv, start, end):
    online = CCXT("BTC/USDT", lv, None, None, AUTYPE.NONE).make_klu(bar(ms(start)))
    offline = CStockFileReader("BTC/USDT", lv, None, None, AUTYPE.NONE).make_klu(*bar(ms(start)))
    assert online.time.ts == offline.time.ts == ms(end) / 1000
    for klu in (online, offline):
        assert klu.open_ms == ms(start)
        assert klu.close_ms == klu.available_at_ms == ms(end)
        assert klu.is_final is True


class CExchange:
    id = "binance"
    options = {"defaultType": "spot"}

    def __init__(self, rows):
        self.rows = rows

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        return [r for r in self.rows if since is None or r[0] >= since][:limit]


@pytest.mark.parametrize("now,expected", [
    ("2024-01-01T00:59", 0),
    ("2024-01-01T01:00", 1),
    ("2024-01-01T01:59", 1),
    ("2024-01-01T02:00", 2),
])
def test_online_reader_excludes_partial_bars(monkeypatch, now, expected):
    monkeypatch.setattr(CCXT, "exchange", CExchange([bar(ms("2024-01-01T00:00")),
                                                     bar(ms("2024-01-01T01:00"))]))
    api = CCXT("BTC/USDT", KL_TYPE.K_60M, now_ms=lambda: ms(now))
    assert len(list(api.get_kl_data())) == expected


def test_offline_reader_does_not_publish_partial_legacy_rows(source_env, monkeypatch):
    from OfflineData.offline_data_util import CKLineDB
    import OfflineData.offline_data_util as storage
    path = source_env / "kline.db"
    with CKLineDB(str(path)) as db:
        db.bind_source(SOURCE)
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, [bar(ms("2024-01-01T00:00"))])
    monkeypatch.setattr(storage, "default_db_path", lambda: str(path))
    api = CStockFileReader("BTC/USDT", KL_TYPE.K_60M, now_ms=lambda: ms("2024-01-01T00:59"))
    assert list(api.get_kl_data()) == []


def test_ccxt_snapshot_is_explicitly_provisional(monkeypatch):
    from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
    class CTickerExchange:
        def fetch_tickers(self, symbols):
            return {s: {"last": 100, "timestamp": ms("2024-01-01T00:59")} for s in symbols}
    monkeypatch.setattr(CCCXTSnapshot, "exchange", CTickerExchange())
    klu = CCCXTSnapshot.query(["BTC/USDT"], return_klu=True)["BTC/USDT"]
    assert klu.is_final is False
    assert klu.time.ts == ms("2024-01-01T00:59") / 1000


def test_incremental_update_refetches_and_repairs_the_last_bar():
    from OfflineData.ccxt_update import update_symbol
    first = ms("2024-01-01T00:00")
    exchange = CExchange([bar(first)])
    with CKLineDB(":memory:") as db:
        assert update_symbol("BTC/USDT", KL_TYPE.K_60M, db, exchange, "2024-01-01", False,
                             now_ms=lambda: first + 3_600_000) == 1
        exchange.rows[0] = bar(first, 105)
        assert update_symbol("BTC/USDT", KL_TYPE.K_60M, db, exchange, verbose=False,
                             now_ms=lambda: first + 3_600_000) == 1
        assert db.query_klines("BTC/USDT", KL_TYPE.K_60M)[0][4] == 105
        assert update_symbol("BTC/USDT", KL_TYPE.K_60M, db, exchange, verbose=False,
                             now_ms=lambda: first + 3_600_000) == 0
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 1


def test_incremental_update_only_persists_closed_bars():
    from OfflineData.ccxt_update import update_symbol
    start = ms("2024-01-01T00:00")
    with CKLineDB(":memory:") as db:
        update_symbol("BTC/USDT", KL_TYPE.K_60M, db, CExchange([bar(start), bar(start + 3_600_000)]),
                      "2024-01-01", False, now_ms=lambda: start + 3_600_000)
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 1


@pytest.mark.parametrize("rows", [
    [bar(ms("2024-01-01T01:00")), bar(ms("2024-01-01T00:00"))],
    [bar(ms("2024-01-01T00:00")), bar(ms("2024-01-01T00:00"))],
    [bar(ms("2024-01-01T00:00")), bar(ms("2024-01-01T02:00"))],
    [[ms("2024-01-01T00:00"), 100, 110, 90, float("nan"), 1]],
    [[ms("2024-01-01T00:00"), 100, 110, 90, 120, 1]],
    [[ms("2024-01-01T00:00"), 100, 110, 90, 100, -1]],
    [bar(ms("2024-01-01T00:01"))],
])
def test_bad_exchange_page_is_rejected_before_any_rows_are_committed(rows):
    from OfflineData.ccxt_update import update_symbol
    with CKLineDB(":memory:") as db:
        with pytest.raises(CChanException):
            update_symbol("BTC/USDT", KL_TYPE.K_60M, db, CExchange(rows), "2024-01-01", False)
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 0


def test_exchange_pagination_must_advance(monkeypatch):
    import OfflineData.ccxt_update as updater
    monkeypatch.setattr(updater, "PAGE_LIMIT", 2)
    class CRepeatingExchange(CExchange):
        calls = 0

        def fetch_ohlcv(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 2:
                pytest.fail("重复页在第二次读取时就必须拒绝，不能无限重试")
            return self.rows
    rows = [bar(ms("2024-01-01T00:00")), bar(ms("2024-01-01T01:00"))]
    with CKLineDB(":memory:") as db:
        with pytest.raises(CChanException, match="前进|回绕"):
            updater.update_symbol("BTC/USDT", KL_TYPE.K_60M, db, CRepeatingExchange(rows),
                                  "2024-01-01", False)
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 2


@pytest.mark.parametrize("changed", [
    {"exchange": "okx"}, {"market_type": "swap", "settle": "USDT"},
    {"price_type": "mark"}, {"settle": "BTC"},
])
def test_one_database_cannot_silently_mix_sources(tmp_path, changed):
    path = tmp_path / "source.db"
    with CKLineDB(str(path)) as db:
        db.bind_source(SOURCE)
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, [bar(ms("2024-01-01T00:00"))])
    with CKLineDB(str(path)) as db:
        with pytest.raises(CChanException, match="来源"):
            db.bind_source({**SOURCE, **changed})
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 1


def test_legacy_rows_require_an_explicit_source_mapping():
    with CKLineDB(":memory:") as db:
        rows = [bar(ms("2024-01-01T00:00"))]
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, rows)
        with pytest.raises(CChanException, match="旧库|来源"):
            db.bind_source(SOURCE)
        assert db.query_klines("BTC/USDT", KL_TYPE.K_60M) == [tuple(rows[0])]
        db.bind_source(SOURCE, adopt_legacy=True)
        assert db.source_identity == SOURCE
        assert db.query_klines("BTC/USDT", KL_TYPE.K_60M) == [tuple(rows[0])]


@pytest.fixture()
def source_env(tmp_path, monkeypatch):
    from Config.EnvConfig import CEnv
    conf = tmp_path / "config.yaml"
    conf.write_text(f"offline_data:\n  sqlite_path: {(tmp_path / 'kline.db').as_posix()}\n"
                    f"  root: {tmp_path.as_posix()}\nccxt:\n  exchange: binance\n  default_type: spot\n",
                    encoding="utf-8")
    monkeypatch.setenv("CHANPY_CONFIG", str(conf))
    CEnv.reset_instance()
    yield tmp_path
    CEnv.reset_instance()


@pytest.mark.parametrize("source", [None, {**SOURCE, "exchange": "okx"}])
def test_offline_reader_rejects_unknown_or_wrong_source(source_env, source):
    with CKLineDB(str(source_env / "kline.db")) as db:
        if source is not None:
            db.bind_source(source)
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, [bar(ms("2024-01-01T00:00"))])
    with pytest.raises(CChanException, match="来源"):
        list(CStockFileReader("BTC/USDT", KL_TYPE.K_60M).get_kl_data())


def test_csv_fallback_requires_explicit_source_declaration(source_env):
    path = source_env / "BTC_USDT_60m.csv"
    path.write_text("datetime,open,high,low,close,volume\n2024-01-01 00:00:00,100,110,90,100,1\n", encoding="utf-8")
    with pytest.raises(CChanException, match="来源"):
        list(CStockFileReader("BTC/USDT", KL_TYPE.K_60M).get_kl_data())


def test_legacy_migration_keeps_a_backup_and_all_original_rows(tmp_path):
    from OfflineData.offline_data_util import migrate_legacy_source
    path, backup = tmp_path / "legacy.db", tmp_path / "legacy.backup.db"
    rows = [bar(ms("2024-01-01T00:00"))]
    with CKLineDB(str(path)) as db:
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, rows)
    migrate_legacy_source(str(path), SOURCE, str(backup))
    with CKLineDB(str(path)) as db, CKLineDB(str(backup)) as old:
        assert db.source_identity == SOURCE
        assert old.source_identity is None
        assert db.query_klines("BTC/USDT", KL_TYPE.K_60M) == old.query_klines("BTC/USDT", KL_TYPE.K_60M)
    with pytest.raises((CChanException, FileExistsError)):
        migrate_legacy_source(str(path), SOURCE, str(backup))


@pytest.mark.parametrize("kind,status", [("empty", "no_data"), ("stale", "stale"),
                                          ("gap", "gap"), ("inactive", "inactive"), ("ok", "ready")])
def test_quality_reports_why_data_is_not_ready(kind, status):
    first = ms("2024-01-01T00:00")
    with CKLineDB(":memory:") as db:
        db.bind_source(SOURCE)
        rows = [] if kind == "empty" else [bar(first)]
        if kind == "gap":
            rows.append(bar(first + 7_200_000))
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, rows)
        quality = db.inspect_quality("BTC/USDT", KL_TYPE.K_60M,
                                     now_ms=first + (10_800_000 if kind in {"stale", "gap"} else 3_600_000),
                                     market_active=kind != "inactive")
        assert quality["status"] == status
        assert quality["ready"] is (status == "ready")


def test_provisional_bars_cannot_enter_confirmed_chan_calculation():
    from Chan import CChan
    from ChanConfig import CChanConfig
    klu = CCXT("BTC/USDT", KL_TYPE.K_60M, now_ms=lambda: ms("2024-01-01T00:59")).make_klu(bar(ms("2024-01-01T00:00")))
    chan = CChan("BTC/USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({"trigger_step": True}))
    with pytest.raises(CChanException, match="未收盘|provisional"):
        chan.trigger_load({KL_TYPE.K_60M: [klu]})
    assert len(chan[0]) == 0


def test_deepcopy_preserves_crypto_publication_metadata():
    from copy import deepcopy
    klu = CCXT("BTC/USDT", KL_TYPE.K_60M).make_klu(bar(ms("2024-01-01T00:00")))
    klu.macd = klu.boll = None
    cloned = deepcopy(klu)
    assert (cloned.open_ms, cloned.close_ms, cloned.available_at_ms, cloned.is_final) == (
        klu.open_ms, klu.close_ms, klu.available_at_ms, klu.is_final)


def test_online_reader_rejects_a_repeating_page(monkeypatch):
    import DataAPI.ccxt as reader
    monkeypatch.setattr(reader, "PAGE_LIMIT", 2)
    class CRepeatingExchange(CExchange):
        calls = 0
        @staticmethod
        def parse8601(value):
            return ms("2024-01-01T00:00")

        def fetch_ohlcv(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 2:
                pytest.fail("reader 必须拒绝重复页")
            return self.rows
    monkeypatch.setattr(CCXT, "exchange", CRepeatingExchange([
        bar(ms("2024-01-01T00:00")), bar(ms("2024-01-01T01:00"))]))
    with pytest.raises(CChanException, match="前进|回绕"):
        list(CCXT("BTC/USDT", KL_TYPE.K_60M, begin_date="2024-01-01").get_kl_data())


def test_updater_rejects_mislabeled_market_type():
    from OfflineData.ccxt_update import update_symbol
    with CKLineDB(":memory:") as db:
        with pytest.raises(CChanException, match="来源"):
            update_symbol("BTC/USDT:USDT", KL_TYPE.K_60M, db, CExchange([]), verbose=False,
                          source={**SOURCE, "market_type": "swap", "settle": "USDT"})
        assert db.source_identity is None


def test_interrupted_download_resumes_from_last_verified_bar(monkeypatch):
    import ccxt
    import OfflineData.ccxt_update as updater
    monkeypatch.setattr(updater, "PAGE_LIMIT", 2)
    start = ms("2024-01-01T00:00")
    rows = [bar(start + i * 3_600_000) for i in range(4)]
    class CInterruptedExchange(CExchange):
        def fetch_ohlcv(self, *args, **kwargs):
            if kwargs["since"] > rows[1][0]:
                raise ccxt.NetworkError("fixture interruption")
            return super().fetch_ohlcv(*args, **kwargs)
    with CKLineDB(":memory:") as db:
        with pytest.raises(CChanException, match="网络"):
            updater.update_symbol("BTC/USDT", KL_TYPE.K_60M, db, CInterruptedExchange(rows),
                                  "2024-01-01", False)
        assert db.last_ts("BTC/USDT", KL_TYPE.K_60M) == rows[1][0]
        assert updater.update_symbol("BTC/USDT", KL_TYPE.K_60M, db, CExchange(rows), verbose=False) == 2
        assert db.count("BTC/USDT", KL_TYPE.K_60M) == 4


def test_csv_reader_rejects_a_gap_instead_of_hiding_it(source_env):
    from Config.EnvConfig import CEnv
    CEnv.get_instance().conf["offline_data"]["source_identity"] = SOURCE
    (source_env / "BTC_USDT_60m.csv").write_text(
        "datetime,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,100,110,90,100,1\n"
        "2024-01-01 02:00:00,100,110,90,100,1\n", encoding="utf-8")
    with pytest.raises(CChanException, match="缺口"):
        list(CStockFileReader("BTC/USDT", KL_TYPE.K_60M).get_kl_data())


def test_perpetual_csv_uses_a_windows_safe_settlement_symbol(source_env):
    from Config.EnvConfig import CEnv
    CEnv.get_instance().conf["offline_data"]["source_identity"] = {
        **SOURCE, "market_type": "swap", "settle": "USDT"}
    (source_env / "BTC_USDT_USDT_60m.csv").write_text(
        "datetime,open,high,low,close,volume\n2024-01-01 00:00:00,100,110,90,100,1\n", encoding="utf-8")
    klus = list(CStockFileReader("BTC/USDT:USDT", KL_TYPE.K_60M).get_kl_data())
    assert len(klus) == 1
    assert klus[0].close_ms == ms("2024-01-01T01:00")


def test_online_and_offline_bars_retain_the_verified_market_identity(source_env, monkeypatch):
    row = bar(ms("2024-01-01T00:00"))
    with CKLineDB(str(source_env / "kline.db")) as db:
        db.bind_source(SOURCE)
        db.upsert_klines("BTC/USDT", KL_TYPE.K_60M, [row])
    monkeypatch.setattr(CCXT, "exchange", CExchange([row]))
    online = list(CCXT("BTC/USDT", KL_TYPE.K_60M).get_kl_data())[0]
    offline = list(CStockFileReader("BTC/USDT", KL_TYPE.K_60M).get_kl_data())[0]
    assert online.source_identity == offline.source_identity == SOURCE
    online.macd = online.boll = None
    from copy import deepcopy
    cloned = deepcopy(online)
    cloned.source_identity["exchange"] = "okx"
    assert online.source_identity == SOURCE


def test_existing_stock_csv_fallback_does_not_require_crypto_identity(source_env):
    (source_env / "sz.test_day.csv").write_text(
        "datetime,open,high,low,close,volume\n2024-01-01,100,110,90,100,1\n", encoding="utf-8")
    bars = list(CStockFileReader("sz.test", KL_TYPE.K_DAY).get_kl_data())
    assert len(bars) == 1
    assert not hasattr(bars[0], "source_identity")
