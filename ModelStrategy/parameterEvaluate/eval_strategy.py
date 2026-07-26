"""策略离线收益评估:输入(阈值/止盈止损/bsp类型过滤/股票池/时段),
输出盈亏比/交易次数/最大回撤/平均收益/持仓成本/各票明细"""
from typing import Dict, List, Optional

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


class CEvalConfig:
    def __init__(
        self,
        code_list: List[str],
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
        data_src=DATA_SRC.CSV,
        lv_list: Optional[List[KL_TYPE]] = None,
        autype: AUTYPE = AUTYPE.QFQ,
        chan_config: Optional[Dict] = None,     # 含 cbsp_strategy 的 CChanConfig 字典
        score_thred: Optional[float] = None,    # 评估侧分数过滤(cbsp.score 存在时生效)
        bsp_type_filter: Optional[str] = None,  # 如 "1,1p":只统计这些类型的 cbsp
        max_sl_rate: Optional[float] = None,    # 止损(并入 strategy_para)
        max_profit_rate: Optional[float] = None,  # 止盈(并入 strategy_para)
        strategy_para: Optional[Dict] = None,   # 其他策略参数覆盖
        lv_idx: int = 0,                        # 交易发生在哪个级别(多级别联立策略用,如 1=中周期)
    ):
        self.code_list = code_list
        self.begin_time = begin_time
        self.end_time = end_time
        self.data_src = data_src
        self.lv_list = lv_list or [KL_TYPE.K_DAY]
        self.autype = autype
        self.chan_config = dict(chan_config or {})
        self.score_thred = score_thred
        self.bsp_type_filter = bsp_type_filter
        self.lv_idx = lv_idx
        para = dict(self.chan_config.get("strategy_para", {}))
        para.update(strategy_para or {})
        if max_sl_rate is not None:
            para["max_sl_rate"] = max_sl_rate
        if max_profit_rate is not None:
            para["max_profit_rate"] = max_profit_rate
        self.chan_config["strategy_para"] = para


class CTradeRecord:
    def __init__(self, code, cbsp, close_price, close_ts, reason, is_closed):
        self.code = code
        self.is_buy = cbsp.is_buy
        self.bs_type = cbsp.bs_type
        self.open_time = cbsp.klu.time
        self.open_ts = cbsp.klu.time.ts
        self.open_price = cbsp.open_price
        self.close_price = close_price
        self.close_ts = close_ts
        self.reason = reason
        self.is_closed = is_closed  # False 表示评估结束时仍持仓,按最后收盘价强平
        self.score = cbsp.score
        self.profit_rate = cbsp.profit_with_final(close_price)  # %,分批平仓按数量加权
        self.mae = cbsp.mae  # 最大不利偏移(%)
        self.mfe = cbsp.mfe  # 最大有利偏移(%)

    def to_dict(self):
        return {
            "code": self.code, "is_buy": self.is_buy, "bs_type": self.bs_type,
            "open_time": self.open_time.to_str(), "open_price": self.open_price,
            "close_price": self.close_price, "profit_rate": self.profit_rate,
            "reason": self.reason, "is_closed": self.is_closed, "score": self.score,
            "mae": self.mae, "mfe": self.mfe,
        }


class CEvalResult:
    def __init__(self, trades: List[CTradeRecord]):
        self.trades = trades
        profits = [t.profit_rate for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        self.trade_cnt = len(trades)
        self.win_cnt = len(wins)
        self.lose_cnt = len(losses)
        self.win_rate = self.win_cnt / self.trade_cnt if trades else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        self.profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else (float("inf") if wins else 0.0)
        self.total_profit_rate = sum(profits)
        self.avg_profit_rate = sum(profits) / len(profits) if profits else 0.0
        self.max_drawdown = self._cal_max_drawdown(trades)
        self.max_hold_cnt = self._cal_max_hold_cnt(trades)  # 最大同时持仓数(持仓成本按每笔1单位名义)
        self.per_code: Dict[str, Dict] = {}
        for t in trades:
            d = self.per_code.setdefault(t.code, {"trade_cnt": 0, "win_cnt": 0, "total_profit_rate": 0.0})
            d["trade_cnt"] += 1
            d["win_cnt"] += int(t.profit_rate > 0)
            d["total_profit_rate"] += t.profit_rate

    @staticmethod
    def _cal_max_drawdown(trades: List[CTradeRecord]) -> float:
        # 按平仓时间累计收益率曲线的最大回撤(百分点)
        curve = sorted(trades, key=lambda t: t.close_ts)
        cum = peak = 0.0
        max_dd = 0.0
        for t in curve:
            cum += t.profit_rate
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        return max_dd

    @staticmethod
    def _cal_max_hold_cnt(trades: List[CTradeRecord]) -> int:
        events = []
        for t in trades:
            events.append((t.open_ts, 1))
            events.append((t.close_ts, -1))
        events.sort(key=lambda x: (x[0], -x[1]))
        cur = peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        return peak

    def to_dict(self) -> dict:
        return {
            "trade_cnt": self.trade_cnt, "win_cnt": self.win_cnt, "lose_cnt": self.lose_cnt,
            "win_rate": self.win_rate, "profit_loss_ratio": self.profit_loss_ratio,
            "total_profit_rate": self.total_profit_rate, "avg_profit_rate": self.avg_profit_rate,
            "max_drawdown": self.max_drawdown, "max_hold_cnt": self.max_hold_cnt,
            "per_code": self.per_code,
        }

    def __str__(self):
        pl = f"{self.profit_loss_ratio:.2f}" if self.profit_loss_ratio != float("inf") else "inf"
        lines = [
            "===== 策略评估报告 =====",
            f"交易次数: {self.trade_cnt}  胜率: {self.win_rate*100:.1f}%  盈亏比: {pl}",
            f"总收益率: {self.total_profit_rate:.2f}%  平均收益率: {self.avg_profit_rate:.2f}%",
            f"最大回撤: {self.max_drawdown:.2f}%  最大同时持仓: {self.max_hold_cnt}",
            "---- 各票明细 ----",
        ]
        lines.extend(
            f"  {code}: 交易{d['trade_cnt']}次 胜{d['win_cnt']}次 总收益{d['total_profit_rate']:.2f}%"
            for code, d in self.per_code.items()
        )
        return "\n".join(lines)


def eval_strategy(conf: CEvalConfig) -> CEvalResult:
    trades: List[CTradeRecord] = []
    type_filter = set(conf.bsp_type_filter.split(",")) if conf.bsp_type_filter else None
    for code in conf.code_list:
        chan_conf = dict(conf.chan_config)
        if chan_conf.get("cbsp_strategy") is None:
            from CustomBuySellPoint.CustomStrategy import CCustomStrategy
            chan_conf["cbsp_strategy"] = CCustomStrategy
        chan = CChan(
            code=code,
            begin_time=conf.begin_time,
            end_time=conf.end_time,
            data_src=conf.data_src,
            lv_list=conf.lv_list,
            config=CChanConfig(chan_conf),
            autype=conf.autype,
        )
        last_klu = chan[conf.lv_idx][-1][-1]
        strategy = chan[conf.lv_idx].cbsp_strategy
        assert strategy is not None
        for cbsp in strategy:
            if type_filter is not None and not (set(cbsp.bs_type.replace("q", "").replace("z", "").split(",")) & type_filter):
                continue
            if conf.score_thred is not None and cbsp.score is not None and cbsp.score < conf.score_thred:
                continue
            if cbsp.is_cover:
                last_action = cbsp.close_actions[-1]
                trades.append(CTradeRecord(code, cbsp, last_action.price, last_action.klu.time.ts, last_action.reason, True))
            else:  # 未平仓的按评估期末收盘价强平
                trades.append(CTradeRecord(code, cbsp, last_klu.close, last_klu.time.ts, "eval_end", False))
    return CEvalResult(trades)
