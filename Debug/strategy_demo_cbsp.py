import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from Plot.PlotDriver import CPlotDriver

if __name__ == "__main__":
    """
    M1 验收 demo:CCustomStrategy 跑 sz.000001 csv 离线数据,产出 cbsp 并画图(虚线箭头+√标记)
    """
    code = "sz.000001"
    lv_list = [KL_TYPE.K_DAY]

    config = CChanConfig({
        "trigger_step": False,
        "divergence_rate": float("inf"),
        "min_zs_cnt": 0,
        "bs_type": "1,2,3a,1p,2s,3b",
        "cbsp_strategy": CCustomStrategy,
        "strategy_para": {
            "strict_open": True,
            "use_qjt": True,
            "short_shelling": True,
            "judge_on_close": True,
        },
    })

    chan = CChan(
        code=code,
        begin_time="2022-01-01",
        end_time=None,
        data_src=DATA_SRC.CSV,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    strategy = chan[0].cbsp_strategy
    print(f"共产出 {len(strategy)} 个 cbsp:")
    for cbsp in strategy:
        print(f"  {cbsp}")

    plot_config = {
        "plot_kline": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_zs": True,
        "plot_bsp": True,
        "plot_cbsp": True,
    }
    plot_para = {
        "cbsp": {
            "plot_cover": True,
            "show_profit": True,
        },
        "figure": {
            "x_range": 300,
        },
    }
    driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
    out_path = os.path.join(os.path.dirname(__file__), "cbsp_demo.png")
    driver.save2img(out_path)
    print(f"画图保存至 {out_path}")
