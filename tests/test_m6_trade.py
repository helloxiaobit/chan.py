"""M6 验收测试:CChanDB状态机、CCXT引擎dry-run模拟撮合、Trade/Script 完整生命周期、重启恢复"""
import os

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Config.EnvConfig import CEnv
from CustomBuySellPoint.Signal import CSignal
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.Script.CheckOpenScore import check_open_score
from Trade.Script.ClosePreErrorOpen import close_pre_error_open
from Trade.Script.MakeOpenTrade import make_open_trade
from Trade.Script.OpenConfig import COpenConfig
from Trade.Script.RealTimeTracker import real_time_track
from Trade.Script.SignalMonitor import run_signal_monitor
from Trade.Script.UpdatePeakPrice import update_peak_price

from .conftest import make_klu


@pytest.fixture()
def tmp_env(tmp_path):
    conf_path = tmp_path / "config.yaml"
    conf_path.write_text(
        f"""
db:
  type: sqlite
  sqlite_path: {(tmp_path / 'trade.db').as_posix()}
offline_data:
  root: {tmp_path.as_posix()}
  sqlite_path: {(tmp_path / 'kline.db').as_posix()}
snapshot_engine: ccxt
ccxt:
  exchange: binance
notify:
  backend: none
trade:
  code_list: ["TEST/USDT"]
  lv: K_DAY
  bench_price: 1000
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


def make_signal(code="TEST/USDT", is_buy=True, open_thred=100.0, sl_thred=95.0, target="2020/01/01"):
    from Common.CTime import CTime
    bar = {"year": 2020, "month": 1, "day": 1, "open": 99, "high": 100, "low": 98, "close": 99.5, "volume": 1}
    return CSignal(
        code=code, lv=KL_TYPE.K_DAY, is_buy=is_buy, bs_type="1",
        sig_klu=make_klu(bar), open_thred=open_thred, sl_thred=sl_thred,
        target_klu_time=CTime(2020, 1, 1, 0, 0),
    )


def test_db_signal_lifecycle(tmp_env):
    db = CChanDB()
    sid = db.add_signal(make_signal())
    assert sid > 0
    # 重复信号拒绝
    with pytest.raises(CChanException) as e:
        db.add_signal(make_signal())
    assert e.value.errcode == ErrCode.SIGNAL_EXISTED
    assert len(db.get_watching_signals()) == 1
    db.unwatch(sid, "test")
    assert db.get_watching_signals() == []
    assert db.get_record(sid)["unwatch_reason"] == "test"
    # unwatch 后可重新入库
    sid2 = db.add_signal(make_signal())
    assert sid2 != sid
    db.close()


def test_db_open_cover_flow(tmp_env):
    db = CChanDB()
    sid = db.add_signal(make_signal())
    db.mark_open(sid, open_price=101.0, quota=9.9, order_id="o1", score_before=0.8)
    rec = db.get_record(sid)
    assert rec["is_open"] and rec["status"] == "open"
    # 重复开仓拒绝
    with pytest.raises(CChanException) as e:
        db.mark_open(sid, 102.0, 1.0)
    assert e.value.errcode == ErrCode.RECORD_ALREADY_OPENED
    # 峰值更新(多头只升不降)
    assert db.update_peak_price(sid, 110.0) == 110.0
    assert db.update_peak_price(sid, 105.0) == 110.0
    # 平仓
    db.mark_cover_order(sid, "c1", 9.9, "stop_loss")
    db.mark_cover_done(sid, 96.0)
    rec = db.get_record(sid)
    assert rec["status"] == "cover" and rec["cover_avg_price"] == 96.0
    assert db.get_open_records() == []
    db.close()


def test_quota_gen():
    gen = CBenchPriceQuotaGen(bench_price=1000.0)
    assert gen.get_quota("BTC/USDT", 50000.0) == pytest.approx(0.02)  # crypto 按名义金额
    assert gen.get_quota("sz.000001", 10.0, lot_size=100) == 100  # 1手即达标
    assert gen.get_quota("sz.000001", 3.0, lot_size=100) == 400  # 凑4手

def test_engine_dry_run_basic(tmp_env):
    db = CChanDB()
    engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(1000.0))
    assert engine.dry_run  # 未配置 api_key 自动 dry_run
    engine.set_sim_price("TEST/USDT", 100.0)
    order = engine.place_order("TEST/USDT", True, 10.0, 100.0)
    assert order.status == "closed" and order.avg_price == 100.0
    assert engine.get_position("TEST/USDT") == 10.0
    assert engine.get_balance()["USDT"] == pytest.approx(99000.0)
    order2 = engine.place_order("TEST/USDT", False, 10.0, 110.0)
    assert engine.get_position("TEST/USDT") == 0.0
    assert engine.get_balance()["USDT"] == pytest.approx(100100.0)
    db.close()


def test_full_dryrun_lifecycle(tmp_env):
    """M6 核心验收:信号入库→突破→开仓→跟踪→止损平仓,DB记录完整"""
    db = CChanDB()
    engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(1000.0))
    open_conf = COpenConfig()  # demo: max_sl_rate=0.05, max_profit_rate=0.15

    # 1. 信号入库
    sid = db.add_signal(make_signal(open_thred=100.0, sl_thred=95.0))
    assert db.get_record(sid)["status"] == "signal"

    # 2. 价格未突破 → 不开仓
    assert make_open_trade(db, engine, open_conf, price_map={"TEST/USDT": 99.0}) == []
    # 3. 突破 → 开仓
    opened = make_open_trade(db, engine, open_conf, price_map={"TEST/USDT": 100.5})
    assert opened == [sid]
    rec = db.get_record(sid)
    assert rec["is_open"] and rec["open_price"] == 100.5 and rec["quota"] > 0
    assert engine.get_position("TEST/USDT") == pytest.approx(rec["quota"])
    # 已开仓的信号不会重复开仓
    assert make_open_trade(db, engine, open_conf, price_map={"TEST/USDT": 101.0}) == []

    # 4. 后验通过(完成K线收盘价仍突破)
    assert check_open_score(db, open_conf, close_map={"TEST/USDT": 101.0}) == []
    assert not db.get_record(sid)["open_err"]

    # 5. 跟踪:价格上行更新峰值,不触发平仓
    update_peak_price(db, price_map={"TEST/USDT": 103.0})
    assert db.get_record(sid)["peak_price_after_open"] == 103.0
    assert real_time_track(db, engine, open_conf, price_map={"TEST/USDT": 102.0}) == []

    # 6. 跌破止损价 → 平仓
    covered = real_time_track(db, engine, open_conf, price_map={"TEST/USDT": 94.0})
    assert covered == [sid]
    rec = db.get_record(sid)
    assert rec["status"] == "cover"
    assert rec["cover_reason"] == "stop_loss"
    assert rec["cover_avg_price"] == 94.0
    assert engine.get_position("TEST/USDT") == pytest.approx(0.0)
    db.close()


def test_check_open_score_error_flow(tmp_env):
    """后验失败 → open_err → ClosePreErrorOpen 尽快平掉"""
    db = CChanDB()
    engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(1000.0))
    sid = db.add_signal(make_signal(open_thred=100.0))
    make_open_trade(db, engine, COpenConfig(), price_map={"TEST/USDT": 100.5})
    # 完成K线收盘价回落到阈值下方 → 后验失败
    err_ids = check_open_score(db, COpenConfig(), close_map={"TEST/USDT": 99.0})
    assert err_ids == [sid]
    assert db.get_record(sid)["open_err"]
    closed = close_pre_error_open(db, engine, price_map={"TEST/USDT": 99.0})
    assert closed == [sid]
    assert db.get_record(sid)["status"] == "cover"
    assert "open_err" in db.get_record(sid)["cover_reason"]
    db.close()


def test_restore_no_duplicate_open(tmp_env):
    """重启恢复现场:重建 db/engine 后已开仓记录仍在,不重复开仓"""
    db = CChanDB()
    engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(1000.0))
    sid = db.add_signal(make_signal(open_thred=100.0))
    make_open_trade(db, engine, COpenConfig(), price_map={"TEST/USDT": 100.5})
    db.close()
    # 模拟重启
    db2 = CChanDB()
    engine2 = CCCXTTradeEngine(db2, quota_gen=CBenchPriceQuotaGen(1000.0))
    engine2.restore()
    recs = db2.get_open_records()
    assert len(recs) == 1 and recs[0]["id"] == sid
    # watching 信号列表为空(已开仓),不会重复开仓
    assert make_open_trade(db2, engine2, COpenConfig(), price_map={"TEST/USDT": 101.0}) == []
    db2.close()


def test_signal_monitor_on_synthetic(tmp_env, synthetic_bars):
    """SignalMonitor 全流程:离线数据→缠论→bsp_signal→入库/清理(信号有无取决于数据形态)"""
    from OfflineData.offline_data_util import CKLineDB, parse_dt_to_ts
    with CKLineDB(str(tmp_env / "kline.db")) as kdb:
        rows = [
            (parse_dt_to_ts(f"{b['year']:04}-{b['month']:02}-{b['day']:02}"),
             b["open"], b["high"], b["low"], b["close"], b["volume"])
            for b in synthetic_bars
        ]
        kdb.upsert_klines("TEST/USDT", KL_TYPE.K_DAY, rows)
    db = CChanDB()
    stat = run_signal_monitor(db, code_list=["TEST/USDT"], lv=KL_TYPE.K_DAY, push=False)
    assert set(stat.keys()) == {"added", "existed", "unwatched", "failed"}
    assert stat["failed"] == 0
    # 再跑一遍:新信号变 existed,无重复入库
    stat2 = run_signal_monitor(db, code_list=["TEST/USDT"], lv=KL_TYPE.K_DAY, push=False)
    assert stat2["added"] == 0
    assert stat2["existed"] == stat["added"]
    db.close()


def test_send_msg_none_backend(tmp_env):
    from Common.send_msg_cmd import send_msg
    assert send_msg("测试", "内容", level="INFO") is True


def test_market_open():
    from Common.TradeUtil import is_market_open
    assert is_market_open("crypto") is True
