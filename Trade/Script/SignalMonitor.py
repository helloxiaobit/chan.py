"""信号例行:全池计算 bsp_signal → 信号入库 / 失效清理 / 推送统计

用法: python -m Trade.Script.SignalMonitor
"""
import os
import sys
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.send_msg_cmd import send_msg
from Trade.db_util import CChanDB

from .StaticsChanConfig import get_statics_chan_config, get_trade_conf


def run_signal_monitor(
    db: CChanDB,
    code_list: Optional[List[str]] = None,
    lv: Optional[KL_TYPE] = None,
    lv_list: Optional[List[KL_TYPE]] = None,
    data_src: str = "custom:OfflineDataAPI.CStockFileReader",
    begin_time: Optional[str] = None,
    chan_conf_extra: Optional[Dict] = None,
    push: bool = True,
) -> Dict[str, int]:
    trade_conf = get_trade_conf()
    code_list = code_list or trade_conf["code_list"]
    if lv_list is None:
        lv_list = [lv] if lv is not None else trade_conf["lv_list"]
    trade_lv = 1 if len(lv_list) >= 2 and trade_conf["strategy"] == "multi_lv" else 0
    stat = {"added": 0, "existed": 0, "unwatched": 0, "failed": 0}
    for code in code_list:
        try:
            chan = CChan(
                code=code,
                begin_time=begin_time,
                data_src=data_src,
                lv_list=lv_list,
                config=CChanConfig(get_statics_chan_config(chan_conf_extra)),
                autype=AUTYPE.NONE,
            )
        except CChanException as e:
            print(f"[SignalMonitor] {code} 计算失败: {e}")
            stat["failed"] += 1
            continue
        strategy = chan[trade_lv].cbsp_strategy
        assert strategy is not None
        signals = strategy.bsp_signal(chan, trade_lv)
        valid_targets = {str(sig.target_klu_time) for sig in signals}
        for sig in signals:
            try:
                db.add_signal(sig)
                stat["added"] += 1
            except CChanException as e:
                if e.errcode == ErrCode.SIGNAL_EXISTED:
                    stat["existed"] += 1
                else:
                    raise
        # 失效清理:该 code 下 watching 但已不在当前信号集合的记录
        for rec in db.get_watching_signals(code):
            if rec["target_klu_time"] not in valid_targets:
                db.unwatch(rec["id"], reason="signal_expired")
                stat["unwatched"] += 1
    if push:
        send_msg("SignalMonitor", f"新增{stat['added']} 已存在{stat['existed']} "
                                  f"失效{stat['unwatched']} 失败{stat['failed']}")
    return stat


if __name__ == "__main__":
    run_signal_monitor(CChanDB())
