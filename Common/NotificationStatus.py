"""Scoped software notification counters; never delivery or trading certification."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from CustomBuySellPoint.Decision import canonical_bytes


BACKENDS = ("dingtalk", "email", "gotify", "none", "telegram", "unknown", "wecom")
MODULES = ("OfflineData.ccxt_update", "Trade.Script.RestoreOrders", "Trade.Script.SignalMonitor", "Trade.Script.MakeOpenTrade",
    "Trade.Script.CheckOpenScore", "Trade.Script.ClosePreErrorOpen", "Trade.Script.RealTimeTracker", "Trade.Script.RetradeCoverOrder")
SCHEMA = "chan-notification-summary-v1"
MAX_BYTES = 16_384
_current = ContextVar("chan_notification_observer", default=None)


class CNotificationSummary:
    def __init__(self):
        self._counts = {}

    def _attempt(self, backend):
        row = self._counts.setdefault(backend, {"attempted": 0, "accepted": 0, "failed": 0, "local_only": 0})
        row["attempted"] += 1

    def _result(self, backend, outcome):
        self._counts[backend][outcome] += 1

    def snapshot(self):
        return [{"backend": key, **row} for key, row in sorted(self._counts.items())]

    @property
    def complete(self):
        return all(row["attempted"] == row["accepted"]+row["failed"]+row["local_only"] for row in self._counts.values())


@contextmanager
def observe_notifications():
    summary = CNotificationSummary()
    token = _current.set(summary)
    try:
        yield summary
    finally:
        _current.reset(token)


def notification_attempt(backend):
    summary = _current.get()
    if summary is not None:
        summary._attempt(backend)


def notification_result(backend, outcome):
    summary = _current.get()
    if summary is not None:
        summary._result(backend, outcome)


def notification_stage_identity(run_id, stage_id, module):
    if (any(type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None for value in (run_id, stage_id))
            or type(module) is not str or module not in MODULES):
        raise ValueError("invalid notification stage identity")
    return {"run_id": run_id, "stage_id": stage_id, "module": module}


@contextmanager
def notification_report_path():
    directory = None
    try:
        directory = TemporaryDirectory(prefix="chanpy-notification-", ignore_cleanup_errors=True)
    except OSError:
        pass
    try:
        yield None if directory is None else Path(directory.name)/"summary.json"
    finally:
        if directory is not None:
            try:
                directory.cleanup()
            except OSError:
                pass  # 仅含固定状态的临时产物清理失败不能跳过原账户管理。


def _validate(payload):
    if (not isinstance(payload, dict) or set(payload) != {"run_id", "stage_id", "module", "complete", "counts"}
            or type(payload["complete"]) is not bool
            or not isinstance(payload["counts"], list) or len(payload["counts"]) > len(BACKENDS)):
        raise ValueError("invalid notification summary")
    notification_stage_identity(payload["run_id"], payload["stage_id"], payload["module"])
    keys, complete = [], True
    for row in payload["counts"]:
        if (not isinstance(row, dict) or set(row) != {"backend", "attempted", "accepted", "failed", "local_only"}
                or row["backend"] not in BACKENDS
                or any(type(row[key]) is not int or not 0 <= row[key] < 2**63 for key in ("attempted", "accepted", "failed", "local_only"))
                or row["attempted"] == 0 or row["accepted"]+row["failed"]+row["local_only"] > row["attempted"]
                or (row["backend"] != "none" and row["local_only"] != 0)
                or (row["backend"] in {"none", "unknown"} and row["accepted"] != 0)):
            raise ValueError("invalid notification counts")
        keys.append(row["backend"])
        complete = complete and row["attempted"] == row["accepted"]+row["failed"]+row["local_only"]
    if keys != sorted(set(keys)) or payload["complete"] != complete:
        raise ValueError("inconsistent notification summary")


def publish_notification_summary(path, summary, *, run_id, stage_id, module):
    from ModelStrategy.parameterEvaluate.artifact import write_json_once
    if type(summary) is not CNotificationSummary:
        raise ValueError("original notification observer required")
    payload = {"run_id": run_id, "stage_id": stage_id, "module": module,
        "complete": summary.complete, "counts": summary.snapshot()}
    _validate(payload)
    return write_json_once(path, {"schema": SCHEMA, "payload": payload,
        "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()})


def read_notification_summary(path, *, run_id, stage_id, module):
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_BYTES+1)
        doc = json.loads(raw)
        if (len(raw) > MAX_BYTES or canonical_bytes(doc) != raw
                or not isinstance(doc, dict) or set(doc) != {"schema", "payload", "payload_sha256"}
                or doc["schema"] != SCHEMA):
            raise ValueError("invalid notification bytes")
        payload = doc["payload"]
        _validate(payload)
        if (any(payload[key] != value for key, value in {"run_id": run_id, "stage_id": stage_id, "module": module}.items())
                or hashlib.sha256(canonical_bytes(payload)).hexdigest() != doc["payload_sha256"]):
            raise ValueError("notification identity mismatch")
        return {"state": "complete" if payload["complete"] else "incomplete", "counts": payload["counts"]}
    except Exception:
        return {"state": "unavailable", "counts": None}  # 不把缺失/坏观察升级为零失败。
