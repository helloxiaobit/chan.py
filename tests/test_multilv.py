"""多级别联立策略测试:K_4H枚举、结束时间对齐、CMultiLevelStrategy、load vs trigger一致性"""
import math
import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import check_kltype_order, kltype_lt_day
from Config.EnvConfig import CEnv
from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
from KLine.KLine_Unit import CKLine_Unit
from OfflineData.offline_data_util import KLTYPE_TO_MS, CKLineDB

BASE_CONF = {
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs_type": "1,2,3a,1p,2s,3b",
    "cbsp_strategy": CMultiLevelStrategy,
    "kl_data_check": False,
}
LV_LIST = [KL_TYPE.K_4H, KL_TYPE.K_60M, KL_TYPE.K_15M]
START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def gen_15m_bars(n_4h=250, seed=7):
    """确定性合成15分钟K线(开始时间口径),n_4h 根 4h = n_4h*16 根 15m"""
    rnd = random.Random(seed)
    bars = []
    prev_close = 100.0
    for i in range(n_4h * 16):
        base = (100 + 30 * math.sin(i / (16 * 17)) + 10 * math.sin(i / (16 * 4.5))
                + 4 * math.sin(i / 9) + i * 0.001)
        close = max(base + rnd.uniform(-0.8, 0.8), 1.0)
        o = prev_close
        h = max(o, close) + rnd.uniform(0, 0.5)
        l = max(min(o, close) - rnd.uniform(0, 0.5), 0.5)
        ts = int((START + timedelta(minutes=15 * i)).timestamp() * 1000)
        bars.append((ts, round(o, 4), round(h, 4), round(l, 4), round(close, 4), 100.0))
        prev_close = close
    return bars


def aggregate(bars, group):
    res = []
    for i in range(0, len(bars) - len(bars) % group, group):
        chunk = bars[i:i + group]
        res.append((chunk[0][0], chunk[0][1], max(b[2] for b in chunk),
                    min(b[3] for b in chunk), chunk[-1][4], sum(b[5] for b in chunk)))
    return res


@pytest.fixture(scope="module")
def bars_3lv():
    b15 = gen_15m_bars()
    return {"15m": b15, "1h": aggregate(b15, 4), "4h": aggregate(b15, 16)}


@pytest.fixture()
def tmp_env(tmp_path, bars_3lv):
    conf_path = tmp_path / "config.yaml"
    conf_path.write_text(
        f"""
db:
  type: sqlite
  sqlite_path: {(tmp_path / 'trade.db').as_posix()}
offline_data:
  root: {tmp_path.as_posix()}
  sqlite_path: {(tmp_path / 'kline.db').as_posix()}
notify:
  backend: none
trade:
  code_list: ["TEST/USDT"]
  strategy: multi_lv
  lv_list: [K_4H, K_60M, K_15M]
""", encoding="utf-8")
    old = os.environ.get("CHANPY_CONFIG")
    os.environ["CHANPY_CONFIG"] = str(conf_path)
    CEnv.reset_instance()
    with CKLineDB(str(tmp_path / "kline.db")) as db:
        db.upsert_klines("TEST/USDT", KL_TYPE.K_15M, bars_3lv["15m"])
        db.upsert_klines("TEST/USDT", KL_TYPE.K_60M, bars_3lv["1h"])
        db.upsert_klines("TEST/USDT", KL_TYPE.K_4H, bars_3lv["4h"])
    yield tmp_path
    if old is None:
        os.environ.pop("CHANPY_CONFIG", None)
    else:
        os.environ["CHANPY_CONFIG"] = old
    CEnv.reset_instance()


def test_kltype_order_with_4h():
    check_kltype_order(LV_LIST)  # 不抛即通过
    check_kltype_order([KL_TYPE.K_DAY, KL_TYPE.K_4H, KL_TYPE.K_2H, KL_TYPE.K_60M])
    assert kltype_lt_day(KL_TYPE.K_4H) and kltype_lt_day(KL_TYPE.K_2H)
    assert KLTYPE_TO_MS[KL_TYPE.K_4H] == 4 * 3600 * 1000


def test_offline_reader_endtime(tmp_env, bars_3lv):
    """日内级别读出的K线时间应为结束时间(开始时间+周期)"""
    from DataAPI.OfflineDataAPI import CStockFileReader
    api = CStockFileReader("TEST/USDT", k_type=KL_TYPE.K_4H)
    first = next(api.get_kl_data())
    open_dt = datetime.fromtimestamp(bars_3lv["4h"][0][0] / 1000, tz=timezone.utc)
    assert (first.time.year, first.time.month, first.time.day, first.time.hour) == \
        (open_dt.year, open_dt.month, open_dt.day, open_dt.hour + 4)


def make_klu_end(ts_open, o, h, l, c, v, lv):
    dt = datetime.fromtimestamp((ts_open + KLTYPE_TO_MS[lv]) / 1000, tz=timezone.utc)
    return CKLine_Unit({
        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False),
        DATA_FIELD.FIELD_OPEN: o, DATA_FIELD.FIELD_HIGH: h,
        DATA_FIELD.FIELD_LOW: l, DATA_FIELD.FIELD_CLOSE: c,
        DATA_FIELD.FIELD_VOLUME: v,
    })


def run_load(tmp_env, conf_extra=None):
    return CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        config=CChanConfig({**BASE_CONF, **(conf_extra or {})}),
        autype=AUTYPE.NONE,
    )


def cbsp_sig(chan, lv):
    return [(c.klu.idx, c.is_buy, c.bs_type, round(c.open_price, 6), c.is_cover)
            for c in chan[lv].cbsp_strategy]


def test_multilv_alignment_and_roles(tmp_env):
    chan = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": False}})
    # 父子链:15M → 1H → 4H
    last_15m = chan[2][-1][-1]
    assert last_15m.sup_kl is not None and last_15m.sup_kl.kl_type == KL_TYPE.K_60M
    assert last_15m.sup_kl.sup_kl is not None and last_15m.sup_kl.sup_kl.kl_type == KL_TYPE.K_4H
    # 各级别结构齐全
    for lv in range(3):
        assert len(chan[lv].bi_list) > 5, f"lv{lv} 笔太少"
    # 角色:4H(趋势)不开仓;15M(入场)只有1类标记;1H(交易)产生交易
    assert len(chan[0].cbsp_strategy) == 0
    marks = list(chan[2].cbsp_strategy)
    assert len(marks) > 0, "入场级别应有1类标记"
    assert all({t.lstrip('q') for t in m.bs_type.split(',')} & {"1", "1p"} for m in marks)
    trades = list(chan[1].cbsp_strategy)
    assert len(trades) > 0, "放宽区间套确认后交易级别应有交易"
    for t in trades:
        assert t.sl_price is not None


def test_multilv_qjt_marks(tmp_env):
    """开启区间套确认:成交的交易应带 q 前缀(区间套买卖点)"""
    chan = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": True}})
    trades = list(chan[1].cbsp_strategy)
    for t in trades:
        assert t.bs_type.startswith("q"), f"区间套确认下交易类型应带q前缀: {t.bs_type}"


def test_multilv_short_shelling_off(tmp_env):
    chan = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": False, "short_shelling": False}})
    assert all(t.is_buy for t in chan[1].cbsp_strategy)


def test_multilv_consistency_load_vs_trigger(tmp_env, bars_3lv):
    """最高验收:三级联立策略下 load 与 trigger 逐4hK线投喂,各级别结构与交易完全一致"""
    conf = {**BASE_CONF, "strategy_para": {"require_sub_confirm": False}}
    chan_a = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": False}})

    chan_b = CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        config=CChanConfig({**conf, "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    b15, b1h, b4h = bars_3lv["15m"], bars_3lv["1h"], bars_3lv["4h"]
    for i, bar4h in enumerate(b4h):
        chan_b.trigger_load({
            KL_TYPE.K_4H: [make_klu_end(*bar4h, KL_TYPE.K_4H)],
            KL_TYPE.K_60M: [make_klu_end(*b, KL_TYPE.K_60M) for b in b1h[i * 4:(i + 1) * 4]],
            KL_TYPE.K_15M: [make_klu_end(*b, KL_TYPE.K_15M) for b in b15[i * 16:(i + 1) * 16]],
        })
    for lv in range(3):
        bi_a = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.is_sure) for bi in chan_a[lv].bi_list]
        bi_b = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.is_sure) for bi in chan_b[lv].bi_list]
        assert bi_a == bi_b, f"lv{lv} 笔不一致"
        assert cbsp_sig(chan_a, lv) == cbsp_sig(chan_b, lv), f"lv{lv} cbsp不一致"


def test_zone_entry_mode(tmp_env):
    """SMC限价入场:成交的交易带z前缀,挂单价优于突破价,止损在正确一侧"""
    chan = run_load(tmp_env, {"strategy_para": {"entry_mode": "zone", "require_sub_confirm": False}})
    strategy = chan[1].cbsp_strategy
    assert len(strategy.opened_bsp_klu_idx) > 0, "应至少挂过限价单"
    trades = list(strategy)
    assert len(trades) > 0, "合成数据上限价单应有成交"
    for t in trades:
        assert t.bs_type.startswith("z"), f"zone成交应带z前缀: {t.bs_type}"
        assert t.sl_price is not None
        if t.is_buy:
            assert t.open_price > t.sl_price
        else:
            assert t.open_price < t.sl_price


def test_zone_entry_consistency(tmp_env, bars_3lv):
    """zone模式的 load vs trigger 一致性(限价单状态机确定性)"""
    para = {"entry_mode": "zone", "require_sub_confirm": False}
    chan_a = run_load(tmp_env, {"strategy_para": dict(para)})
    chan_b = CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        config=CChanConfig({**BASE_CONF, "strategy_para": dict(para), "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    b15, b1h, b4h = bars_3lv["15m"], bars_3lv["1h"], bars_3lv["4h"]
    for i, bar4h in enumerate(b4h):
        chan_b.trigger_load({
            KL_TYPE.K_4H: [make_klu_end(*bar4h, KL_TYPE.K_4H)],
            KL_TYPE.K_60M: [make_klu_end(*b, KL_TYPE.K_60M) for b in b1h[i * 4:(i + 1) * 4]],
            KL_TYPE.K_15M: [make_klu_end(*b, KL_TYPE.K_15M) for b in b15[i * 16:(i + 1) * 16]],
        })
    assert cbsp_sig(chan_a, 1) == cbsp_sig(chan_b, 1)


def test_weighted_profit_partial_close():
    from CustomBuySellPoint.CustomBSP import CCustomBSP
    t0 = 1700000000000
    k_open = make_klu_end(t0, 100, 101, 99, 100, 1, KL_TYPE.K_60M)
    k1 = make_klu_end(t0 + 3600000, 100, 111, 100, 110, 1, KL_TYPE.K_60M)
    k2 = make_klu_end(t0 + 7200000, 110, 121, 109, 120, 1, KL_TYPE.K_60M)
    cbsp = CCustomBSP(bsp=None, klu=k_open, bs_type="1", is_buy=True, price=100.0, sl_price=95.0)
    cbsp.do_close(110.0, k1, reason="partial_tp", quota=0.5)  # 一半在+10%
    assert not cbsp.is_cover
    cbsp.do_close(120.0, k2, reason="take_profit")            # 剩余在+20%
    assert cbsp.is_cover
    assert cbsp.profit == pytest.approx(0.5 * 10 + 0.5 * 20)  # 加权 15%
    assert cbsp.profit_with_final(999) == pytest.approx(15)   # 已全平,final价无关


def test_bos_zone_mode(tmp_env):
    """BOS→回撤 v2:先突破确认再挂回撤限价,chase 防错过;限价成交z前缀,追入原类型"""
    chan = run_load(tmp_env, {"strategy_para": {
        "entry_mode": "bos_zone", "require_sub_confirm": False, "chase_bars": 4}})
    strategy = chan[1].cbsp_strategy
    trades = list(strategy)
    assert len(trades) > 0, "bos_zone(带chase)应有成交"
    for t in trades:
        assert t.sl_price is not None
        if t.is_buy:
            assert t.open_price > t.sl_price
        else:
            assert t.open_price < t.sl_price


def test_exit_engine(tmp_env):
    """出场引擎:结构化目标/分批止盈/时间止损产生对应平仓动作,加权收益生效"""
    chan = run_load(tmp_env, {"strategy_para": {
        "require_sub_confirm": False,
        "exit_target_mode": "liq",
        "partial_tp_r": 1.0,
        "trail_after_r": 1.5,
        "time_stop_bars": 12,
    }})
    trades = list(chan[1].cbsp_strategy)
    assert len(trades) > 0
    reasons = {ca.reason for t in trades for ca in t.close_actions}
    assert reasons & {"take_profit", "partial_tp", "time_stop"}, f"出场引擎未生效: {reasons}"
    # 有分批的交易,加权收益应等于手工加权
    for t in trades:
        if t.is_cover and len(t.close_actions) >= 2 and t.close_actions[0].quota == 0.5:
            manual = 0.5 * t.profit_at(t.close_actions[0].price) + 0.5 * t.profit_at(t.close_actions[-1].price)
            assert t.profit == pytest.approx(manual)
            break
    # MAE/MFE 已采集
    assert any(t.mfe > 0 or t.mae < 0 for t in trades)


def test_new_features_consistency(tmp_env, bars_3lv):
    """bos_zone + 出场引擎全开下的 load vs trigger 一致性(最高验收)"""
    para = {"entry_mode": "bos_zone", "require_sub_confirm": False, "chase_bars": 4,
            "exit_target_mode": "liq", "partial_tp_r": 1.0, "trail_after_r": 1.5,
            "time_stop_bars": 12}
    chan_a = run_load(tmp_env, {"strategy_para": dict(para)})
    chan_b = CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        config=CChanConfig({**BASE_CONF, "strategy_para": dict(para), "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    b15, b1h, b4h = bars_3lv["15m"], bars_3lv["1h"], bars_3lv["4h"]
    for i, bar4h in enumerate(b4h):
        chan_b.trigger_load({
            KL_TYPE.K_4H: [make_klu_end(*bar4h, KL_TYPE.K_4H)],
            KL_TYPE.K_60M: [make_klu_end(*b, KL_TYPE.K_60M) for b in b1h[i * 4:(i + 1) * 4]],
            KL_TYPE.K_15M: [make_klu_end(*b, KL_TYPE.K_15M) for b in b15[i * 16:(i + 1) * 16]],
        })
    sig_a = [(c.klu.idx, c.is_buy, c.bs_type, round(c.open_price, 6), c.is_cover,
              [(ca.reason, round(ca.price, 6), ca.quota) for ca in c.close_actions])
             for c in chan_a[1].cbsp_strategy]
    sig_b = [(c.klu.idx, c.is_buy, c.bs_type, round(c.open_price, 6), c.is_cover,
              [(ca.reason, round(ca.price, 6), ca.quota) for ca in c.close_actions])
             for c in chan_b[1].cbsp_strategy]
    assert sig_a == sig_b


def test_strategy_ensemble_equivalence(tmp_env):
    """集合评估的正确性铁闸:同一变体在 ensemble 中与单独跑结果逐笔一致"""
    from CustomBuySellPoint.StrategyEnsemble import CStrategyEnsemble
    chan_e = CChan(
        code="TEST/USDT",
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        config=CChanConfig({**BASE_CONF, "cbsp_strategy": CStrategyEnsemble, "strategy_para": {
            "skip_features": True,
            "require_sub_confirm": False,
            "variants": [
                {"name": "base"},
                {"name": "intrabar", "sl_intrabar": True},
            ],
        }}),
        autype=AUTYPE.NONE,
    )
    ensemble = chan_e[1].cbsp_strategy
    assert len(ensemble.variants) == 2

    def sig(strategy):
        return [(c.klu.idx, c.is_buy, c.bs_type, round(c.open_price, 6), c.is_cover,
                 [(ca.reason, round(ca.price, 6)) for ca in c.close_actions])
                for c in strategy.cbsp_lst]

    # 与单独跑逐笔比对
    for name, para in (("base", {}), ("intrabar", {"sl_intrabar": True})):
        chan_s = run_load(tmp_env, {"strategy_para": {
            "skip_features": True, "require_sub_confirm": False, **para}})
        assert sig(ensemble.get_variant(name)) == sig(chan_s[1].cbsp_strategy), f"变体{name}与单独跑不一致"
    # 两个变体应有差异(否则测试无意义)——盘中止损会改变部分平仓
    assert sig(ensemble.get_variant("base")) != sig(ensemble.get_variant("intrabar"))


def test_regime_stamp_and_silent(tmp_env):
    """每笔交易带 regime 戳;silent 模式交易数不多于基线且戳全为 trend"""
    chan = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": False}})
    trades = list(chan[1].cbsp_strategy)
    assert len(trades) > 0
    assert all(t.exit_state.get("regime") in ("trend", "range") for t in trades)
    chan_s = run_load(tmp_env, {"strategy_para": {"require_sub_confirm": False, "regime_mode": "silent"}})
    trades_s = list(chan_s[1].cbsp_strategy)
    assert len(trades_s) <= len(trades)
    assert all(t.exit_state.get("regime") == "trend" for t in trades_s)


def test_multilv_eval_lv_idx(tmp_env):
    from ModelStrategy.parameterEvaluate.eval_strategy import CEvalConfig, eval_strategy
    res = eval_strategy(CEvalConfig(
        code_list=["TEST/USDT"],
        data_src="custom:OfflineDataAPI.CStockFileReader",
        lv_list=LV_LIST,
        autype=AUTYPE.NONE,
        chan_config=BASE_CONF,
        strategy_para={"require_sub_confirm": False},
        lv_idx=1,
    ))
    assert res.trade_cnt > 0
    assert res.trade_cnt == len(res.trades)


def test_signal_monitor_multilv(tmp_env):
    from Trade.db_util import CChanDB
    from Trade.Script.SignalMonitor import run_signal_monitor
    db = CChanDB()
    stat = run_signal_monitor(db, push=False)
    assert stat["failed"] == 0
    db.close()
