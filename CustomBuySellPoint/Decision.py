"""策略决策的有限 canonical 字节。身份与内容摘要分离，便于精确定位漂移。"""
import hashlib
import json

from Common.ChanException import CChanException, ErrCode

SCHEMA = "chan-decision-v1"
IDENTITY_KEYS = {"kind", "code", "level", "decision_ms", "anchor_ms", "is_buy", "is_segbsp",
                 "bs_type", "sequence", "parent_event_id", "market"}


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CChanException("决策证据必须是有限 finite JSON", ErrCode.FEATURE_ERROR) from exc


def decision_identity(kind, code, level, decision_ms, is_buy, bs_type, *, is_segbsp=False,
                      anchor_ms=None, sequence=0, parent_event_id=None, market=None):
    return {"kind": kind, "code": code, "level": getattr(level, "name", str(level)),
            "decision_ms": decision_ms, "anchor_ms": decision_ms if anchor_ms is None else anchor_ms,
            "is_buy": is_buy, "is_segbsp": is_segbsp, "bs_type": bs_type,
            "sequence": sequence, "parent_event_id": parent_event_id, "market": market}


def _validate_identity(identity):
    if (not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS
            or identity["kind"] not in {"open", "exit", "signal"}
            or any(not isinstance(identity[k], str) or not identity[k] for k in ("code", "level", "bs_type"))
            or any(type(identity[k]) is not int or identity[k] < 0 for k in ("decision_ms", "anchor_ms", "sequence"))
            or identity["anchor_ms"] > identity["decision_ms"]
            or type(identity["is_buy"]) is not bool or type(identity["is_segbsp"]) is not bool
            or (identity["kind"] == "exit" and (not isinstance(identity["parent_event_id"], str)
                                                or len(identity["parent_event_id"]) != 64))
            or (identity["kind"] != "exit" and identity["parent_event_id"] is not None)):
        raise CChanException("决策身份 identity 不完整或时间无效", ErrCode.FEATURE_ERROR)
    if identity["market"] is not None:
        from OfflineData.offline_data_util import validate_source_identity
        validate_source_identity(identity["market"])


def make_decision(identity, payload):
    _validate_identity(identity)
    if not isinstance(payload, dict):
        raise CChanException("决策 payload 必须是对象", ErrCode.FEATURE_ERROR)
    return canonical_bytes({"schema": SCHEMA,
                            "event_id": hashlib.sha256(canonical_bytes(identity)).hexdigest(),
                            "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                            "identity": identity, "payload": payload})


def read_decision(raw):
    try:
        record = json.loads(raw)
        if (type(raw) is not bytes or not isinstance(record, dict)
                or set(record) != {"schema", "event_id", "payload_sha256", "identity", "payload"}
                or record["schema"] != SCHEMA or make_decision(record["identity"], record["payload"]) != raw):
            raise CChanException("决策 canonical 字节、身份或内容摘要不一致", ErrCode.FEATURE_ERROR)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CChanException("决策证据 JSON 无效", ErrCode.FEATURE_ERROR) from exc
    return record  # 新对象；调用者修改解码结果不会影响已发布字节


def bar_snapshot(klu):
    if getattr(klu, "is_final", True) is False:
        raise CChanException("provisional K线不能发布确认决策", ErrCode.FEATURE_ERROR)
    result = {"time_ms": int(klu.time.ts * 1000), "open": klu.open, "high": klu.high,
              "low": klu.low, "close": klu.close}
    if hasattr(klu, "source_identity"):
        from OfflineData.offline_data_util import validate_source_identity
        result["market"] = validate_source_identity(klu.source_identity)
    for key in ("open_ms", "close_ms", "available_at_ms"):
        if hasattr(klu, key):
            result[key] = getattr(klu, key)
    if (result.get("available_at_ms", result["time_ms"]) > result["time_ms"]
            or result.get("close_ms", result["time_ms"]) != result["time_ms"]):
        raise CChanException("K线在记录时刻尚不可用 available，或收盘时钟不一致", ErrCode.FEATURE_ERROR)
    canonical_bytes(result)
    return result
