"""单写入器软件 paper 检查点；不是交易所、网络原子性或掉电认证。"""
import hashlib
import json
import math
import os
import platform
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from ModelStrategy.parameterEvaluate.artifact import write_once
from .LinearPaperAccount import CLinearPaperAccount, restore_linear_paper_account


SCHEMA = "chan-paper-server-checkpoint-v1"
_ORDER_FIELDS = {"code", "is_buy", "price", "reduce_only", "result", "fill_plan", "next_fill",
    "paper_contract", "paper_position_id", "paper_role", "paper_reason"}
_RESULT_FIELDS = {"order_id", "client_order_id", "requested", "filled", "avg_price", "status"}


class _PaperSequence:
    """Explicit next server ID; no opaque iterator/pickle state in checkpoints."""
    def __init__(self, next_value):
        self.next_value = next_value

    def __iter__(self):
        return self

    def __next__(self):
        if type(self.next_value) is not int or not 1 <= self.next_value < 2**63:
            _fail()
        value = self.next_value
        self.next_value += 1
        return value


def _fail():
    raise CChanException("原 paper 服务器状态缺失/损坏/未持久化或身份不符，禁止猜测恢复", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _code(path):
    return _sha(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode())


def _runtime():
    return {"codec_sha256": _code(Path(__file__)),
        "lock_sha256": _code(Path(__file__).with_name("Script")/"RunTradeCycle.py"),
        "python": platform.python_version(), "implementation": platform.python_implementation()}


def _database(path):
    path = Path(path).resolve()
    stat = path.stat()
    if not path.is_file() or stat.st_nlink != 1 or not stat.st_ino:
        _fail()
    return {"path": str(path), "device": stat.st_dev, "inode": stat.st_ino}


def _numeric(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and not value):
        _fail()
    return value


def _plan(value):
    if (not isinstance(value, list) or not value or any(_numeric(item) < 0 for item in value)
            or any(left > right for left, right in zip(value, value[1:]))):
        _fail()


def _state_payload(state):
    if (state.paper_account is None or state.positions or state.last_price or state.balance != {"USDT": 100000.0}
            or type(state.order_id_gen) is not _PaperSequence
            or set(state.orders) != set(state.order_state) or len(state.client_order_ids) != len(state.orders)
            or set(state.client_order_ids.values()) != set(state.orders)):
        _fail()
    orders = []
    for key, order in sorted(state.order_state.items()):
        if (set(vars(order)) != _ORDER_FIELDS or set(vars(order.result)) != _RESULT_FIELDS
                or state.orders[key] is not order.result or key != order.result.order_id
                or state.client_order_ids.get(order.result.client_order_id) != key):
            _fail()
        orders.append({**{field: getattr(order, field) for field in _ORDER_FIELDS if field != "result"},
            "result": vars(order.result)})
    return json.loads(canonical_bytes({"account": state.paper_account.to_dict(), "orders": orders,
        "fill_plans": state.fill_plans, "next_order_sequence": state.order_id_gen.next_value}))


def _restore_state(payload, reference):
    from .CCXTTradeEngine import CSimExchangeState, _SimOrder, verify_paper_order_state
    from .TradeEngine import COrderResult
    if not isinstance(payload, dict) or set(payload) != {"account", "orders", "fill_plans", "next_order_sequence"}:
        _fail()
    account = restore_linear_paper_account(payload["account"])
    sequence = payload["next_order_sequence"]
    if type(sequence) is not int or not 1 <= sequence < 2**63 or not isinstance(payload["orders"], list):
        _fail()
    state = CSimExchangeState(paper_account=account, order_id_gen=_PaperSequence(sequence))
    for row in payload["orders"]:
        if (not isinstance(row, dict) or set(row) != _ORDER_FIELDS or not isinstance(row["result"], dict)
                or set(row["result"]) != _RESULT_FIELDS or type(row["is_buy"]) is not bool
                or type(row["reduce_only"]) is not bool or row["code"] not in account.markets
                or (row["price"] is not None and _numeric(row["price"], positive=True) <= 0)
                or type(row["next_fill"]) is not int or row["next_fill"] < 0
                or row["paper_role"] not in {"maker", "taker"}
                or (row["paper_reason"] is not None and not isinstance(row["paper_reason"], str))
                or not isinstance(row["paper_position_id"], str) or not row["paper_position_id"]):
            _fail()
        _plan(row["fill_plan"])
        result = row["result"]
        _numeric(result["requested"], positive=True)
        _numeric(result["filled"])
        if (not isinstance(result["order_id"], str) or re.fullmatch(r"sim_[1-9][0-9]*", result["order_id"]) is None
                or int(result["order_id"][4:]) >= sequence or not isinstance(result["client_order_id"], str)
                or not result["client_order_id"] or result["client_order_id"] in state.client_order_ids
                or result["order_id"] in state.orders or row["next_fill"] > len(row["fill_plan"])
                or row["paper_contract"].get("schema") != "chan-paper-order-v2"
                or row["paper_contract"].get("paper_store") != reference):
            _fail()
        order = _SimOrder(**{**row, "result": COrderResult(**result)})
        verify_paper_order_state(order, account)
        state.orders[result["order_id"]] = order.result
        state.order_state[result["order_id"]] = order
        state.client_order_ids[result["client_order_id"]] = result["order_id"]
    for effect in account.to_dict()["effects"]:
        request = effect["request"]
        if request["kind"] == "fill":
            match = re.fullmatch(r"fill:(sim_[1-9][0-9]*):(0|[1-9][0-9]*)", request["id"])
            owner = state.order_state.get(match[1]) if match else None
            if owner is None or int(match[2]) >= owner.next_fill:
                _fail()
    if not isinstance(payload["fill_plans"], dict):
        _fail()
    for key, plan in payload["fill_plans"].items():
        if not isinstance(key, str) or not key:
            _fail()
        _plan(plan)
    state.fill_plans = payload["fill_plans"]
    if canonical_bytes(_state_payload(state)) != canonical_bytes(payload):
        _fail()
    return state


class CPersistentPaperState:
    @classmethod
    def create(cls, path, *, account, database):
        if not isinstance(account, CLinearPaperAccount) or account.to_dict()["effects"]:
            _fail()
        return cls._start(path, database, account)

    @classmethod
    def open(cls, path, *, database):
        return cls._start(path, database, None)

    @classmethod
    def _start(cls, path, database, account):
        from .Script.RunTradeCycle import _run_lock
        from .CCXTTradeEngine import CSimExchangeState
        result = cls.__new__(cls)
        result.path = Path(path).resolve()
        result._closed, result._poisoned, result._busy = False, False, None
        result._mutex = threading.Lock()
        result._lock = None
        try:
            db = _database(database)
            if result.path == Path(db["path"]) or not result.path.parent.is_dir():
                _fail()
            result._lock = _run_lock(result.path)
            result._lock.__enter__()
            if account is not None:
                if result.path.exists():
                    _fail()
                result._identity = {"store_id": uuid.uuid4().hex, "path": str(result.path), "database": db, "runtime": _runtime()}
                result.state = CSimExchangeState(paper_account=account, order_id_gen=_PaperSequence(1))
                raw = result._encode()
                write_once(result.path, raw)
            else:
                raw = result.path.read_bytes()
                document = json.loads(raw)
                if (canonical_bytes(document) != raw or set(document) != {"schema", "payload", "payload_sha256"}
                        or document["schema"] != SCHEMA or _sha(canonical_bytes(document["payload"])) != document["payload_sha256"]
                        or set(document["payload"]) != {"identity", "state"}):
                    _fail()
                result._identity = document["payload"]["identity"]
                identity = result._identity
                if (set(identity) != {"store_id", "path", "database", "runtime"} or identity["path"] != str(result.path)
                        or identity["database"] != db or identity["runtime"] != _runtime()
                        or not isinstance(identity["store_id"], str) or re.fullmatch(r"[0-9a-f]{32}", identity["store_id"]) is None):
                    _fail()
                result.state = _restore_state(document["payload"]["state"], result.reference)
            result._raw = raw
            result.state.paper_store = result
            result.assert_current(result.state)
            return result
        except Exception:
            result.close()
            _fail()

    @property
    def reference(self):
        return {"schema": "chan-paper-store-v1", "store_id": self._identity["store_id"]}

    def _encode(self):
        state = _state_payload(self.state)
        _restore_state(state, self.reference)
        payload = {"identity": self._identity, "state": state}
        return canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(canonical_bytes(payload))})

    def assert_current(self, state):
        try:
            if (self._closed or self._poisoned or state is not self.state or state.paper_store is not self
                    or (self._busy is not None and self._busy != threading.get_ident())
                    or self._identity["runtime"] != _runtime() or _database(self._identity["database"]["path"]) != self._identity["database"]
                    or self.path.stat().st_nlink != 1 or self.path.read_bytes() != self._raw
                    or (self._busy is None and self._encode() != self._raw)):
                _fail()
        except Exception:
            _fail()

    def bind_database(self, chan_db):
        try:
            from .AccountRiskStore import _ledger
            if chan_db.db_type != "sqlite":
                _fail()
            actual = next(row["file"] for row in chan_db.db.query("PRAGMA database_list") if row["name"] == "main")
            if _database(actual) != self._identity["database"]:
                _fail()
            self.assert_current(self.state)
            # Reuse the original cross-table journal reader. A flat current
            # position does not erase previously acknowledged server orders.
            with chan_db.db.transaction():
                ledger = _ledger(chan_db)
                seen = set()
                for history in ledger["histories"]:
                    for attempt in history["attempts"]:
                        identity = attempt["identity"]
                        contract = identity["order_contract"] or {}
                        if (contract.get("paper_account") != self.state.paper_account.identity_reference
                                and contract.get("paper_store") != self.reference):
                            continue
                        if (history["gaps"] or attempt["origin"] != "new_intent" or not identity["contract_complete"]
                                or contract.get("schema") != "chan-paper-order-v2"
                                or contract.get("paper_store") != self.reference):
                            _fail()
                        client = identity["client_order_id"]
                        order = self.state.order_state.get(self.state.client_order_ids.get(client))
                        if order is None:
                            last = attempt["events"][-1]["state"]
                            if last["order_id"] is not None or last["filled_qty"] or last["order_status"] not in {"created", "submitting"}:
                                _fail()
                            continue  # An unacknowledged intent remains unknown; never resubmit here.
                        seen.add(client)
                        if (order.paper_contract != contract or order.code != identity["instrument"]
                                or order.paper_position_id != f"{identity['trade_table']}:{identity['record_id']}"
                                or order.is_buy != (bool(identity["is_buy"]) if identity["phase"] == "open" else not bool(identity["is_buy"]))
                                or order.result.requested != identity["requested_qty"]):
                            _fail()
                        for event in attempt["events"]:
                            applied = event["state"]
                            filled = _numeric(applied["filled_qty"])
                            if (applied["order_id"] not in (None, order.result.order_id) or filled > order.result.filled
                                    or (filled and filled == order.result.filled and applied["avg_price"] != order.result.avg_price)
                                    or (applied["order_status"] in {"closed", "canceled", "rejected"}
                                        and (applied["order_status"] != order.result.status or filled != order.result.filled))):
                                _fail()
                if seen != set(self.state.client_order_ids):
                    _fail()
        except Exception:
            _fail()

    def checkpoint(self):
        temporary = None
        try:
            self.assert_current(self.state)
            raw = self._encode()
            if raw == self._raw:
                return
            fd, temporary = tempfile.mkstemp(prefix="."+self.path.name+".", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.read_bytes() != self._raw:
                _fail()
            os.replace(temporary, self.path)
            temporary = None
            self._raw = raw
        except Exception:
            self._poisoned = True
            _fail()
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    self._poisoned = True
                    _fail()

    @contextmanager
    def operation(self, state):
        if not self._mutex.acquire(blocking=False):
            _fail()
        try:
            self.assert_current(state)
            self._busy = threading.get_ident()
            try:
                yield
                self.checkpoint()
            except BaseException:
                try:
                    if self._encode() != self._raw:
                        self._poisoned = True
                except BaseException:
                    self._poisoned = True
                raise
            finally:
                self._busy = None
        finally:
            self._mutex.release()

    def close(self):
        if not self._mutex.acquire(blocking=False):
            _fail()
        try:
            if not self._closed:
                self._closed = True
                if self._lock is not None:
                    self._lock.__exit__(None, None, None)
                    self._lock = None
        finally:
            self._mutex.release()

    def __enter__(self):
        self.assert_current(self.state)
        return self

    def __exit__(self, *_):
        self.close()  # never auto-save an unaccepted/uncommitted mutation on exit


def paper_state_operation(method):
    @wraps(method)
    def checked(engine, *args, **kwargs):
        state = getattr(engine, "sim_state", None)
        store = getattr(state, "paper_store", None)
        if store is None:
            return method(engine, *args, **kwargs)
        with store.operation(state):
            return method(engine, *args, **kwargs)
    return checked
