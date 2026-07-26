"""试题功能:随机截取历史走势出题——"当下你会不会买?",答案回看走势是否走对

用法(README「试题功能」):
    from ExamGenerator import CQuestion
    Q = CQuestion(area='cn', begin_time='2010-01-01', kl_type=KL_TYPE.K_DAY, _config={...})
    if Q.QuestionGenerator(is_buy=True):
        Q.PlotTestFigure()    # 题目:截止到 cbsp 出现那一刻的图
        Q.PlotAnswerFigure()  # 答案:cbsp 之后的完整走势 + cbsp 标记
原理:CustomBuySellPoint/ExamStrategy.py(cbsp 分形完成即输出)。
"""
import os
import random
from typing import Dict, List, Optional

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

# 出题默认股票池(可通过 code_pool 参数自定义)
DEFAULT_POOL = {
    "cn": ["sz.000001", "sz.000002", "sh.600000", "sh.600036", "sh.600519", "sz.000858"],
    "crypto": ["BTC/USDT", "ETH/USDT"],
}
DEFAULT_DATA_SRC = {
    "cn": DATA_SRC.BAO_STOCK,
    "crypto": "custom:OfflineDataAPI.CStockFileReader",
}


class CQuestion:
    def __init__(
        self,
        area: str = 'cn',
        begin_time: str = '2010-01-01',
        kl_type: KL_TYPE = KL_TYPE.K_DAY,
        _config: Optional[Dict] = None,
        code_pool: Optional[List[str]] = None,
        data_src=None,
        autype: AUTYPE = AUTYPE.QFQ,
        seed: Optional[int] = None,
        out_dir: str = ".",
    ):
        self.area = area
        self.begin_time = begin_time
        self.kl_type = kl_type
        self.config = dict(_config or {})
        self.code_pool = code_pool or DEFAULT_POOL.get(area, DEFAULT_POOL["cn"])
        self.data_src = data_src if data_src is not None else DEFAULT_DATA_SRC.get(area, DATA_SRC.BAO_STOCK)
        self.autype = autype
        self.rnd = random.Random(seed)
        self.out_dir = out_dir

        self.code: Optional[str] = None
        self.chan: Optional[CChan] = None          # 全量(答案用)
        self.question_cbsp = None                  # 出题的 cbsp
        self.question_chan: Optional[CChan] = None  # 截止到题目时刻(题目用)

    def make_chan_config(self) -> Dict:
        from CustomBuySellPoint.ExamStrategy import CExamStrategy
        conf = dict(self.config)
        conf["cbsp_strategy"] = CExamStrategy
        return conf

    def QuestionGenerator(self, is_buy: bool = True, max_try: int = 10) -> bool:
        """随机选股生成符合条件的买卖点,成功返回 True"""
        codes = list(self.code_pool)
        self.rnd.shuffle(codes)
        for code in codes[:max_try]:
            try:
                chan = CChan(
                    code=code, begin_time=self.begin_time, data_src=self.data_src,
                    lv_list=[self.kl_type], config=CChanConfig(self.make_chan_config()),
                    autype=self.autype,
                )
            except Exception as e:
                print(f"[CQuestion] {code} 计算失败,跳过: {e}")
                continue
            candidates = [
                cbsp for cbsp in chan[0].cbsp_strategy
                if cbsp.is_buy == is_buy
                # 题目点之后至少留 30 根K线做答案
                and cbsp.klu.idx < chan[0][-1][-1].idx - 30
                and cbsp.klu.idx > 60  # 题目点之前有足够走势
            ]
            if not candidates:
                continue
            self.code = code
            self.chan = chan
            self.question_cbsp = self.rnd.choice(candidates)
            # 题目:重新计算截止到 cbsp 出现时刻的缠论(保证"当下"视角)
            # end_time 为闭区间(csv/baostock 均含当日),截止到 cbsp 出现当日
            self.question_chan = CChan(
                code=code, begin_time=self.begin_time,
                end_time=f"{self.question_cbsp.klu.time.year:04}-{self.question_cbsp.klu.time.month:02}-{self.question_cbsp.klu.time.day:02}",
                data_src=self.data_src, lv_list=[self.kl_type],
                config=CChanConfig(self.make_chan_config()), autype=self.autype,
            )
            return True
        return False

    def PlotTestFigure(self, kl_type_lst=None, x_range: int = 200) -> str:
        """绘制题目(不含未来),返回图片路径"""
        assert self.question_chan is not None, "请先调用 QuestionGenerator"
        return self._plot(self.question_chan, "exam_question.png", show_cbsp=False, x_range=x_range)

    def PlotAnswerFigure(self, x_range: int = 300) -> str:
        """绘制答案(完整走势+cbsp标记),返回图片路径"""
        assert self.chan is not None, "请先调用 QuestionGenerator"
        return self._plot(self.chan, "exam_answer.png", show_cbsp=True, x_range=x_range)

    def _plot(self, chan: CChan, filename: str, show_cbsp: bool, x_range: int) -> str:
        from Plot.PlotDriver import CPlotDriver
        plot_config = {
            "plot_kline": True,
            "plot_bi": True,
            "plot_seg": True,
            "plot_zs": True,
            "plot_bsp": show_cbsp,  # 题目不给形态学bsp提示
            "plot_cbsp": show_cbsp,
        }
        plot_para = {"figure": {"x_range": x_range}}
        driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
        path = os.path.join(self.out_dir, filename)
        driver.save2img(path)
        print(f"[CQuestion] {self.code} → {path}")
        return path


if __name__ == "__main__":
    Q = CQuestion(area='cn', begin_time='2018-01-01', kl_type=KL_TYPE.K_DAY,
                  _config={"min_zs_cnt": 0, "bs_type": '1,1p'},
                  data_src=DATA_SRC.CSV, autype=AUTYPE.NONE,
                  code_pool=["sz.000001"], seed=42)
    if Q.QuestionGenerator(is_buy=True):
        Q.PlotTestFigure()
        Q.PlotAnswerFigure()
    else:
        print("not cbsp found")
