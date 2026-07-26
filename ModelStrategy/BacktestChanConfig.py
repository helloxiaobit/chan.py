from typing import Dict, List, Optional

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


class CBacktestConfig:
    """回测配置:股票池/时间段/级别/缠论配置/标签参数/输出目录"""

    def __init__(
        self,
        code_list: List[str],
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
        data_src=DATA_SRC.CSV,
        lv_list: Optional[List[KL_TYPE]] = None,
        autype: AUTYPE = AUTYPE.QFQ,
        chan_config: Optional[Dict] = None,   # CChanConfig 字典(cbsp_strategy 必填,否则用默认策略)
        output_dir: str = "./backtest_output",
        primary_label: str = "label_bsp_hold",  # 写入 libsvm 的主标签
        label_para: Optional[Dict] = None,
    ):
        self.code_list = code_list
        self.begin_time = begin_time
        self.end_time = end_time
        self.data_src = data_src
        self.lv_list = lv_list or [KL_TYPE.K_DAY]
        self.autype = autype
        self.chan_config: Dict = dict(chan_config or {})
        self.output_dir = output_dir
        self.primary_label = primary_label
        # 标签参数:label_ret_N 的 N 与阈值;label_max_drawdown 的止盈/止损阈值
        self.label_para = {
            "ret_n": 5,           # label_ret_N: 开仓后N根K线
            "ret_thred": 0.02,    # label_ret_N: 收益率阈值(2%)
            "dd_profit": 0.05,    # label_max_drawdown: 止盈线(+5%)
            "dd_loss": 0.03,      # label_max_drawdown: 止损线(-3%)
        }
        self.label_para.update(label_para or {})
