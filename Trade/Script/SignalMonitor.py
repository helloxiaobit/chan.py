"""信号例行:全池计算 bsp_signal → 信号入库 / 失效清理 / 推送统计

用法: python -m Trade.Script.SignalMonitor
"""
import os
import sys
from contextlib import nullcontext
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.send_msg_cmd import send_msg
from Common.KLineTime import utc_now_ms
from Trade.db_util import CChanDB

from .StaticsChanConfig import get_statics_chan_config, get_trade_conf


def _persist_signal_scan(db, code, trade_level, signals):
    stat = {"added": 0, "existed": 0, "unwatched": 0}
    valid_targets = {(sig.lv.name, bool(sig.is_buy), str(sig.target_klu_time)) for sig in signals}
    for sig in signals:
        try:
            db.add_signal(sig)
            stat["added"] += 1
        except CChanException as e:
            if e.errcode != ErrCode.SIGNAL_EXISTED:
                raise
            if db.db_type == "sqlite" and type(sig.decision) is bytes:
                matches = db.get_signal_records(code, sig.lv.name, sig.is_buy, sig.target_klu_time)
            else:
                matches = [rec for rec in db.get_watching_signals(code)
                    if rec["lv"] == sig.lv.name and bool(rec["is_buy"]) == sig.is_buy
                    and rec["target_klu_time"] == str(sig.target_klu_time)]
            if (len(matches) != 1 or type(sig.decision) is not bytes
                    or matches[0].get("signal_decision") != sig.decision.decode("utf-8")):
                raise CChanException("原信号字节不符，拒绝复用或补造历史", ErrCode.FEATURE_ERROR) from None
            stat["existed"] += 1
    # 只有本次实际交易级别的完整机会键才有缺席证据；不清理未扫描级别。
    for rec in db.get_watching_signals(code):
        key = (rec["lv"], bool(rec["is_buy"]), rec["target_klu_time"])
        if rec["lv"] == trade_level.name and key not in valid_targets:
            db.unwatch(rec["id"], reason="signal_expired")
            stat["unwatched"] += 1
    return stat


def run_signal_monitor(
    db: CChanDB,
    code_list: Optional[List[str]] = None,
    lv: Optional[KL_TYPE] = None,
    lv_list: Optional[List[KL_TYPE]] = None,
    data_src: str = "custom:OfflineDataAPI.CStockFileReader",
    begin_time: Optional[str] = None,
    chan_conf_extra: Optional[Dict] = None,
    push: bool = True,
    deployment=None,
    now_ms=None,
) -> Dict[str, int]:
    from .Deployment import CDeployment
    deployment = deployment or CDeployment.configured()
    trade_conf = get_trade_conf(deployment=deployment) if deployment is not None else get_trade_conf()
    code_list = code_list or trade_conf["code_list"]
    if lv_list is None:
        lv_list = [lv] if lv is not None else trade_conf["lv_list"]
    trade_lv = deployment.trade_lv_idx if deployment is not None else (1 if len(lv_list) >= 2 and trade_conf["strategy"] == "multi_lv" else 0)
    if deployment is not None and (list(code_list) != deployment.code_list or lv_list != deployment.lv_list):
        raise CChanException("监控范围不能覆盖部署的 symbol/level", ErrCode.MODEL_ERROR)
    stat = {"added": 0, "existed": 0, "unwatched": 0, "failed": 0}
    for code in code_list:
        try:
            if deployment is None:
                chan = CChan(code=code, begin_time=begin_time, data_src=data_src, lv_list=lv_list,
                    config=CChanConfig(get_statics_chan_config(chan_conf_extra)), autype=AUTYPE.NONE)
            else:
                deployment.check_overrides(chan_conf_extra)
                at_ms = (now_ms or utc_now_ms)()
                chan = deployment.build_chan(code, at_ms)
            strategy = chan[trade_lv].cbsp_strategy
            assert strategy is not None
            if deployment is None:
                signals = strategy.publish_signals(chan, trade_lv)
            else:
                signals = strategy.bsp_signal(chan, trade_lv)
                accepted = [sig for sig in signals if deployment.prepare_signal(chan, sig, observed_ms=at_ms)["passed"]]
                signals = strategy.publish_signals(chan, trade_lv, signals=accepted)
        except CChanException as e:
            print(f"[SignalMonitor] {code} 计算失败: {e}")
            stat["failed"] += 1
            continue
        try:
            with db.db.transaction() if db.db_type == "sqlite" else nullcontext():
                applied = _persist_signal_scan(db, code, lv_list[trade_lv], signals)
        except CChanException:
            stat["failed"] += 1
            print(f"[SignalMonitor] {code} 原信号集合被拒绝，保留旧观察")
            continue
        for name, count in applied.items():
            stat[name] += count
    if push:
        send_msg("SignalMonitor", f"新增{stat['added']} 已存在{stat['existed']} "
                                  f"失效{stat['unwatched']} 失败{stat['failed']}")
    return stat


if __name__ == "__main__":
    chan_db = CChanDB()
    try:
        result = run_signal_monitor(chan_db)
    finally:
        chan_db.close()
    sys.exit(1 if result["failed"] else 0)
