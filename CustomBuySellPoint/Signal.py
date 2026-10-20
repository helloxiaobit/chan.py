from typing import Optional

from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from .Decision import bar_snapshot, bsp_origin_snapshot, decision_identity, make_decision
from Common.ChanException import CChanException, ErrCode


class CSignal:
    """实盘信号:bsp_signal 接口的返回值,描述"下一根K线若满足突破条件即成为 cbsp"

    字段与交易库信号表对齐(SignalMonitor 落库用):
    - code/lv/bstype/is_buy/open_thred(突破价)/sl_thred(止损价)/target_klu_time
    """

    def __init__(
        self,
        code: str,
        lv,
        is_buy: bool,
        bs_type: str,
        sig_klu: CKLine_Unit,
        open_thred: float,
        sl_thred: Optional[float] = None,
        target_klu_time: Optional[CTime] = None,
        score: Optional[float] = None,
        is_segbsp: bool = False,
        reason: str = "",
        bsp=None,
        target_klc=None,
    ):
        self.code = code
        self.lv = lv
        self.is_buy = is_buy
        self.bs_type = bs_type
        self.sig_klu = sig_klu
        self.open_thred = open_thred  # 突破该价格即开仓
        self.sl_thred = sl_thred  # 止损价
        self.target_klu_time = target_klu_time  # 突破目标K线时间
        self.score = score  # 模型分(若有)
        self.is_segbsp = is_segbsp
        self.reason = reason
        self.bsp, self.target_klc = bsp, target_klc
        self.assessment = None
        self.model_artifact_id = self.deployment_id = None
        self.deployment_path = None
        self._decision = None

    @property
    def decision(self):
        return self._decision

    def freeze_decision(self, *, dedupe=None, features=None, decision_ms=None):
        bar = bar_snapshot(self.sig_klu)
        target_ms = int(self.target_klu_time.ts * 1000) if self.target_klu_time is not None else None
        identity = decision_identity("signal", self.code, self.lv,
                                     bar["time_ms"] if decision_ms is None else decision_ms, self.is_buy, self.bs_type,
                                     is_segbsp=self.is_segbsp, anchor_ms=bar["time_ms"], market=bar.get("market"))
        raw = make_decision(identity, {"bar": bar, "target_klu_ms": target_ms, "score": self.score,
                                       "open_thred": self.open_thred, "sl_thred": self.sl_thred,
                                       "reason": self.reason, "features": features if features is not None else
                                           (self.assessment["features"] if self.assessment else {}),
                                       "origin": bsp_origin_snapshot(self.bsp, identity["decision_ms"]),
                                       "assessment": self.assessment, "model_artifact_id": self.model_artifact_id,
                                       "deployment_id": self.deployment_id, "deployment_path": self.deployment_path,
                                       "dedupe": dedupe or {}})
        if self._decision is not None and self._decision != raw:
            raise CChanException("信号身份已发布，不能改写 payload", ErrCode.FEATURE_ERROR)
        self._decision = raw
        return raw

    def __str__(self):
        bs = "buy" if self.is_buy else "sell"
        return f"CSignal[{self.code}] {bs}({self.bs_type}) @{self.sig_klu.time} thred={self.open_thred} sl={self.sl_thred} score={self.score}"
