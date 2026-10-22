"""后验校验:K线完成后复查突破与分数(model_score_after)

开仓往往发生在K线未完成时(盘中价格突破),K线完成后需要复查:
- 完成K线的收盘价是否仍突破 open_thred
- 配置模型时复查分数是否仍达标
不通过则标记 open_err,由 ClosePreErrorOpen 尽快平掉。

用法: python -m Trade.Script.CheckOpenScore
"""
import os
import sys
import json
import math
from typing import Callable, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import bar_close_ms, containing_bar_open_ms, make_crypto_klu, utc_now_ms
from Common.send_msg_cmd import send_msg
from CustomBuySellPoint.Decision import bar_snapshot
from Trade.db_util import CChanDB

from .OpenConfig import COpenConfig


def get_last_closed_kline_close(code: str, lv: KL_TYPE, *, now_ms=None) -> Optional[float]:
    # 显式的“最新已完成”查询；订单后验不再使用这条全库末行路径。
    from OfflineData.offline_data_util import CKLineDB
    with CKLineDB() as db:
        rows = db.query_klines(code, lv)
        at_ms = utc_now_ms() if now_ms is None else now_ms
        closed = [r for r in rows if bar_close_ms(r[0], lv) <= at_ms]
        return closed[-1][4] if closed else None


def corresponding_closed_bar(record, *, now_ms, expected_source=None):
    from OfflineData.offline_data_util import CKLineDB, configured_source_identity
    snapshot = json.loads(record.get("snapshot_before") or "{}")
    observed_ms = snapshot.get("entry_assessment", {}).get("decision_ms", snapshot.get("entry_observed_ms"))
    if type(observed_ms) is not int or observed_ms < 0:
        raise CChanException("开仓缺少明确 UTC 观察时刻，不能猜测对应后验周期", ErrCode.MODEL_ERROR)
    level = KL_TYPE[record["lv"]]
    expected_open = containing_bar_open_ms(observed_ms, level)
    if bar_close_ms(expected_open, level) > now_ms:
        return None
    with CKLineDB() as market:
        market.check_source(expected_source or configured_source_identity(record["stock_code"]))
        rows = market.query_klines(record["stock_code"], level,
                                  begin_ts=expected_open, end_ts=expected_open+1)
        if len(rows) != 1 or rows[0][0] != expected_open:
            raise CChanException("开仓对应 K 线缺失，不得用其他行替代", ErrCode.MODEL_ERROR)
        row = rows[0]
        klu = make_crypto_klu(row, level, now_ms)
        klu.source_identity = market.source_identity
    return bar_snapshot(klu), observed_ms


def check_open_score(
    db: CChanDB,
    open_conf: Optional[COpenConfig] = None,
    close_map: Optional[Dict[str, float]] = None,       # 测试可注入完成K线收盘价
    score_func: Optional[Callable[[dict], float]] = None,  # 配置模型时注入打分函数
    lv: Optional[KL_TYPE] = None,
    now_ms=None,
) -> List[int]:
    from .Deployment import CDeployment
    open_conf = open_conf or COpenConfig()
    err_ids = []
    for rec in db.get_open_records():
        if rec["open_err"]:
            continue
        previous = json.loads(rec.get("snapshot_after") or "{}")
        if previous.get("schema") == "chan-post-check-v1":
            continue
        code = rec["stock_code"]
        at_ms = (now_ms or utc_now_ms)()
        post = None
        score_after = None
        try:
            if rec.get("deployment_id"):
                if close_map is not None or score_func is not None:
                    raise CChanException("绑定模型后验不能注入无周期/版本的价格或分数", ErrCode.MODEL_ERROR)
                deployed = CDeployment(rec["deployment_path"])
                if deployed.deployment_id != rec["deployment_id"] or deployed.model.artifact_id != rec["model_version"]:
                    raise CChanException("后验模型/部署版本漂移", ErrCode.MODEL_ERROR)
                completed = corresponding_closed_bar(rec, now_ms=at_ms, expected_source=deployed.source_identity)
                if completed is None:
                    continue
                bar, observed_ms = completed
                post = {"schema": "chan-post-check-v1", "deployment_id": deployed.deployment_id,
                        "model_artifact_id": deployed.model.artifact_id, "bar": bar,
                        "timing_basis": "entry_observation", "entry_observed_ms": observed_ms, "checked_at_ms": at_ms}
                close = bar["close"]
            elif close_map is not None:
                close = close_map.get(code)
            elif "/" not in code:
                # 股票路径本轮延期，保留既有最新完成行行为，不冒称通过币圈周期验收。
                close = get_last_closed_kline_close(code, lv or KL_TYPE[rec["lv"]], now_ms=at_ms)
            else:
                completed = corresponding_closed_bar(rec, now_ms=at_ms)
                if completed is None:
                    continue
                close = completed[0]["close"]
            if close is not None and (type(close) not in (int, float) or not math.isfinite(close) or close <= 0):
                raise CChanException("后验收盘价必须有限且为正", ErrCode.MODEL_ERROR)
        except (CChanException, ValueError, KeyError) as error:
            db.set_open_err(rec["id"], reason=f"post_evidence_unavailable: {error}")
            err_ids.append(rec["id"])
            continue
        if close is None:
            continue
        breakout = close > rec["open_thred"] if rec["is_buy"] else close < rec["open_thred"]
        if not breakout:
            if post is not None:
                post.update(status="failed", reason="close_did_not_break_out")
                db.set_score_after(rec["id"], None, snapshot=post)
            db.set_open_err(rec["id"], reason=f"K线完成后未突破: close={close} thred={rec['open_thred']}")
            err_ids.append(rec["id"])
            continue
        if post is not None:
            try:
                assessment = deployed.assess_post(rec, post["bar"]["close_ms"])
                post["assessment"] = assessment
                score_after = assessment["score"]
                post["status"] = "passed" if assessment["passed"] else "failed"
                if not assessment["passed"]:
                    raise CChanException("post_score_filtered", ErrCode.MODEL_ERROR)
            except CChanException as error:
                post.update(status="failed", reason=str(error))
                db.set_open_err(rec["id"], reason=f"post_score_rejected: {error}")
                err_ids.append(rec["id"])
            db.set_score_after(rec["id"], score_after, snapshot=post)
            continue
        if score_func is not None:
            score_after = score_func(rec)
            db.set_score_after(rec["id"], score_after)
            if not open_conf.pass_score(score_after):
                db.set_open_err(rec["id"], reason=f"复查分数不达标: {score_after}")
                err_ids.append(rec["id"])
    if err_ids:
        send_msg("CheckOpenScore", f"{len(err_ids)} 条开仓后验失败,待修复: {err_ids}", level="WARNING")
    return err_ids


def main():
    try:
        db = CChanDB()
        try:
            rejected = check_open_score(db, open_conf=COpenConfig.configured())
        finally:
            db.close()
        print(f"CheckOpenScore: rejected={len(rejected)}")
        return 1 if rejected else 0
    except Exception:
        print("CheckOpenScore: original model/bar evidence unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
