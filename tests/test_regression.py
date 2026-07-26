"""回归测试:main.py / Debug demo / App GUI 至少 import 不崩;
main.py 的完整流程用离线合成数据复刻一遍(baostock 需要联网,离线降级)。
"""
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_import_main_module():
    importlib.import_module("main")


@pytest.mark.parametrize("mod", ["strategy_demo", "strategy_demo2", "strategy_demo3", "strategy_demo4"])
def test_import_demo(mod):
    if os.path.join(ROOT, "Debug") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "Debug"))
    importlib.import_module(mod)


@pytest.mark.parametrize("mod", ["strategy_demo5", "strategy_demo6"])
def test_import_ml_demo(mod):
    pytest.importorskip("xgboost")
    if os.path.join(ROOT, "Debug") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "Debug"))
    importlib.import_module(mod)


def test_import_ashare_gui():
    # fork 所有者自有 App,至少 import 不崩(依赖缺失则跳过)
    pytest.importorskip("PyQt6")
    pytest.importorskip("akshare")
    importlib.import_module("App.ashare_bsp_scanner_gui")


def test_main_py_flow_offline(synthetic_csv_code, tmp_path):
    """复刻 main.py 全流程:CChan 计算 + CPlotDriver 画图保存"""
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
    from Plot.PlotDriver import CPlotDriver

    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": '1,2,3a,1p,2s,3b',
        "print_warning": True,
        "zs_algo": "normal",
    })
    plot_config = {
        "plot_kline": True,
        "plot_kline_combine": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_zs": True,
        "plot_bsp": True,
    }
    plot_para = {"figure": {"x_range": 200}}
    chan = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=config,
        autype=AUTYPE.NONE,
    )
    driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
    out = tmp_path / "test.png"
    driver.save2img(str(out))
    assert out.exists() and out.stat().st_size > 0
