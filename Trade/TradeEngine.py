"""交易引擎通用层:CTradeEngine(market, chan_db)

- 频控:两次交易接口调用之间的最小间隔
- 交易时段:wait4MarketOpen(crypto 直通)
- 现场恢复 restore():重启后同步已提交订单状态,不重复开仓
- add_trade(trade_info, price):仓位计算→下单→落库
- 平仓单、订单微调、轮询、推送
具体撮合接口(下单/撤单/查单/余额/持仓)由子类实现(CCXTTradeEngine/FutuTradeEngine)。
"""
import abc
import hashlib
import math
import time
from typing import Dict, List, Optional

from Common.ChanException import CChanException, ErrCode
from Common.send_msg_cmd import send_msg
from Common.TradeUtil import is_market_open
from Common.KLineTime import utc_now_ms

from .db_util import CChanDB
from .OpenQuotaGen import CBenchPriceQuotaGen, COpenQuotaGen


class COrderResult:
    VALID_STATUSES = {"open", "closed", "canceled", "rejected"}

    def __init__(
        self,
        order_id: str,
        filled: float,
        avg_price: Optional[float],
        status: str,
        requested: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ):
        filled = float(filled)
        requested = filled if requested is None else float(requested)
        if (
            not math.isfinite(filled)
            or not math.isfinite(requested)
            or filled < 0
            or requested < 0
            or filled > requested
        ):
            raise CChanException("订单数量无效", ErrCode.PARA_ERROR)
        if status not in self.VALID_STATUSES:
            raise CChanException(f"未知订单状态: {status}", ErrCode.PARA_ERROR)
        self.order_id = order_id
        self.client_order_id = client_order_id
        self.requested = requested    # 引擎内部数量；crypto 一律为币数，CCXT 边界才转张数
        self.filled = filled          # 同一内部单位的累计已成交数量
        self.avg_price = avg_price    # 成交均价
        self.status = status          # open / closed / canceled / rejected


class CTradeEngine(metaclass=abc.ABCMeta):
    def __init__(
        self,
        market: str,
        chan_db: CChanDB,
        quota_gen: Optional[COpenQuotaGen] = None,
        api_interval: float = 0.2,
        push_msg: bool = True,
    ):
        self.market = market  # crypto / cn / hk / us
        self.chan_db = chan_db
        self.quota_gen = quota_gen or CBenchPriceQuotaGen()
        self.api_interval = api_interval
        self.push_msg = push_msg
        self._last_api_ts = 0.0

    # ===== 撮合接口(子类实现)=====
    @abc.abstractmethod
    def place_order(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        price: Optional[float] = None,
        *,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        post_only: bool = False,
        position_side: Optional[str] = None,
    ) -> COrderResult:
        # price=None 为市价单
        ...

    @abc.abstractmethod
    def cancel_order(self, code: str, order_id: str) -> bool:
        ...

    @abc.abstractmethod
    def query_order(
        self,
        code: str,
        order_id: Optional[str] = None,
        *,
        client_order_id: Optional[str] = None,
    ) -> COrderResult:
        ...

    @abc.abstractmethod
    def get_balance(self) -> Dict[str, float]:
        ...

    @abc.abstractmethod
    def get_position(self, code: str) -> float:
        ...

    # ===== 通用逻辑 =====
    def prepare_order(self, code, amount, price, *, reduce_only=False, record=None, post_only=False):
        """提交意图前的单位/精度 hook；股票及旧离线撮合保留原行为。"""
        return amount, price, None

    def rate_limit(self):
        wait = self.api_interval - (time.time() - self._last_api_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_api_ts = time.time()

    def wait4MarketOpen(self, check_interval: float = 60.0, max_wait: Optional[float] = None):
        # crypto 7×24 直通;其他市场等待开盘
        waited = 0.0
        while not is_market_open(self.market):
            if max_wait is not None and waited >= max_wait:
                raise CChanException(f"等待{self.market}开盘超时", ErrCode.TRADE_UNLOCK_FAIL)
            time.sleep(check_interval)
            waited += check_interval

    def make_client_order_id(self, record: dict, phase: str) -> str:
        if phase not in {"open", "close"}:
            raise CChanException("客户端订单阶段无效", ErrCode.PARA_ERROR)
        attempt_field = "open_attempt" if phase == "open" else "cover_attempt"
        attempt = int(record.get(attempt_field) or 0) + 1
        seed = "|".join(
            (
                phase,
                str(record["id"]),
                str(attempt),
                str(record.get("stock_code") or ""),
                str(record.get("add_date") or ""),
            )
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"chanpy-{phase[0]}-{record['id']}-{attempt}-{digest}"

    def _strategy_version(self, record: dict) -> str:
        if record.get("strategy_version"):
            return str(record["strategy_version"])
        policy = getattr(self, "safety_policy", None)
        receipt = getattr(policy, "strategy_receipt", None) or {}
        return str(receipt.get("strategy_id") or "dry-run-unverified")

    def _position_side(self, record: dict) -> str:
        return str(
            record.get("position_side")
            or getattr(self, "position_side", "BOTH")
        ).upper()

    def _query_persisted_order(self, record: dict, phase: str) -> COrderResult:
        if phase == "open":
            order_id = record.get("open_order_id")
            client_id = record.get("open_client_order_id")
        else:
            order_id = record.get("cover_order_id")
            client_id = record.get("cover_client_order_id")
        return self.query_order(
            record["stock_code"],
            order_id,
            client_order_id=client_id,
        )

    def _apply_order_report(self, record_id, phase, order, client_id, attempt):
        """One attempt-bound DB CAS, not submission-status then fill writes."""
        if order.client_order_id is not None and order.client_order_id != client_id:
            raise CChanException("回报客户端号与查询/提交意图不一致", ErrCode.LIST_ORDER_FAIL)
        apply = self.chan_db.apply_open_fill if phase == "open" else self.chan_db.apply_close_fill
        try:
            return apply(record_id, order.filled, order.avg_price, order.status,
                         client_order_id=client_id, order_id=str(order.order_id), expected_attempt=attempt)
        except CChanException as error:
            if error.errcode == ErrCode.PARA_ERROR:
                raise CChanException("成交回报不满足单调/金额契约，禁止重新提交", ErrCode.LIST_ORDER_FAIL) from error
            raise

    def add_trade(self, trade_info: dict, price: float) -> COrderResult:
        """先持久化开仓意图，再提交并应用交易所累计成交量。"""
        record_id = trade_info["id"]
        record = self.chan_db.get_record(record_id)
        code = record["stock_code"]
        snapshot = {"price": price, "entry_observed_ms": trade_info.get("entry_observed_ms", utc_now_ms())}
        score_before = record.get("model_score_before")
        if record.get("deployment_id") or record.get("model_version"):
            from Trade.Script.Deployment import verify_entry_assessment
            assessment = verify_entry_assessment(record, trade_info.get("entry_assessment"), price, self)
            snapshot.update(entry_assessment=assessment, deployment_id=record["deployment_id"],
                            model_version=record["model_version"], entry_observed_ms=assessment["decision_ms"])
            score_before = assessment["score"]
        quota = self.quota_gen.get_quota(code, price)
        if quota <= 0:
            raise CChanException(f"仓位计算为0: {code} price={price}", ErrCode.QUOTA_NOT_ENOUGH)
        quota, order_price, order_contract = self.prepare_order(code, quota, price, record=record)
        client_id = self.make_client_order_id(record, "open")
        position_side = self._position_side(record)
        acquired = self.chan_db.acquire_open_intent(
            record_id,
            requested_qty=quota,
            client_order_id=client_id,
            position_side=position_side,
            strategy_version=self._strategy_version(record),
            risk_multiplier=float(record.get("risk_multiplier") or 1.0),
            score_before=score_before,
            snapshot=snapshot,
            order_contract=order_contract,
        )
        if not acquired:
            raise CChanException(
                f"开仓意图已被其他进程获取 id={record_id}",
                ErrCode.SIGNAL_TRADED,
            )
        self.rate_limit()
        order = self.place_order(
            code,
            bool(record["is_buy"]),
            quota,
            order_price,
            client_order_id=client_id,
            position_side=position_side,
        )
        self._apply_order_report(record_id, "open", order, client_id, int(record.get("open_attempt") or 0)+1)
        if self.push_msg:
            bs = "买开" if record["is_buy"] else "卖开"
            send_msg(
                "开仓订单",
                f"{code} {bs} filled={order.filled}/{order.requested} "
                f"avg={order.avg_price or 'NA'} status={order.status} "
                f"bstype={record['bstype']} id={record_id}",
            )
        return order

    def close_partial_open(
        self, record: dict, price: Optional[float], reason: str
    ) -> Optional[COrderResult]:
        """先终止仍在成交的开仓单，再只平掉已经形成的实际仓位。"""
        record_id = record["id"]
        current = self.chan_db.get_record(record_id)
        if current["status"] != "partially_filled":
            _status = current["status"]
            raise CChanException(
                f"记录状态 {_status} 不是部分开仓",
                ErrCode.PARA_ERROR,
            )

        def apply_snapshot(order: COrderResult) -> dict:
            self._apply_order_report(record_id, "open", order, current.get("open_client_order_id"), current.get("open_attempt"))
            return self.chan_db.get_record(record_id)

        self.rate_limit()
        order = self._query_persisted_order(current, "open")
        current = apply_snapshot(order)
        if current["open_order_status"] == "open":
            if not self.cancel_order(current["stock_code"], order.order_id):
                return None
            confirmed = self._query_persisted_order(current, "open")
            current = apply_snapshot(confirmed)
            if current["open_order_status"] == "open":
                return None
        if current["status"] == "open" and float(current["current_qty"] or 0) > 0:
            return self.cover_trade(current, price, reason)
        return None

    def cover_trade(self, record: dict, price: Optional[float], reason: str) -> COrderResult:
        """先持久化平仓意图，再以 reduce-only 提交当前剩余数量。"""
        record_id = record["id"]
        previous_attempt = record.get("cover_attempt")
        record = self.chan_db.get_record(record_id)
        if (previous_attempt is not None and previous_attempt != (record.get("cover_attempt") or 0)):
            raise CChanException("平仓快照已跨越另一次尝试，必须重查而非刷新重试", ErrCode.SIGNAL_TRADED)
        if previous_attempt is None and record.get("open_order_contract") is not None:
            raise CChanException("合约平仓缺少原尝试快照", ErrCode.SIGNAL_TRADED)
        previous_attempt = record.get("cover_attempt") or 0
        code = record["stock_code"]
        quota = float(record.get("current_qty") or 0)
        if quota <= 0:
            raise CChanException(
                f"当前仓位为 0: id={record_id}", ErrCode.RECORD_NOT_OPENED
            )
        quota, order_price, order_contract = self.prepare_order(code, quota, price, reduce_only=True, record=record)
        client_id = self.make_client_order_id(record, "close")
        acquired = self.chan_db.acquire_close_intent(
            record_id,
            requested_qty=quota,
            client_order_id=client_id,
            reason=reason,
            order_contract=order_contract,
            previous_attempt=previous_attempt,
        )
        if not acquired:
            raise CChanException(
                f"平仓意图已被其他进程获取 id={record_id}",
                ErrCode.SIGNAL_TRADED,
            )
        self.rate_limit()
        order = self.place_order(
            code,
            not bool(record["is_buy"]),
            quota,
            order_price,
            client_order_id=client_id,
            reduce_only=True,
            position_side=self._position_side(record),
        )
        self._apply_order_report(record_id, "close", order, client_id, previous_attempt+1)
        if self.push_msg:
            bs = "卖平" if record["is_buy"] else "买平"
            profit = None
            if order.avg_price and record["open_price"]:
                rate = (order.avg_price - record["open_price"]) / record["open_price"]
                profit = rate * 100 if record["is_buy"] else -rate * 100
            send_msg(
                "平仓订单",
                f"{code} {bs} filled={order.filled}/{order.requested} "
                f"avg={order.avg_price or 'NA'} status={order.status} "
                f"reason={reason} "
                f"profit={f'{profit:.2f}%' if profit is not None else 'NA'} "
                f"id={record_id}",
            )
        return order

    def poll_orders(self, times: int = 3, interval: float = 5.0, adjust_price: bool = True):
        """轮询平仓；最后一轮仅在撤单终态确认后重下剩余数量。"""
        for index in range(times):
            pending = [
                rec for rec in self.chan_db.get_recoverable_records()
                if rec["status"] == "closing"
            ]
            if not pending:
                return
            for rec in pending:
                self.rate_limit()
                try:
                    order = self._query_persisted_order(rec, "close")
                    self._apply_order_report(rec["id"], "close", order, rec.get("cover_client_order_id"), rec.get("cover_attempt"))
                except CChanException as exc:
                    if exc.errcode == ErrCode.LIST_ORDER_FAIL:
                        continue
                    raise
                current = self.chan_db.get_record(rec["id"])
                if (current.get("cover_client_order_id") != rec.get("cover_client_order_id")
                        or current.get("cover_attempt") != rec.get("cover_attempt")):
                    continue
                if current["status"] == "closed":
                    continue
                if not adjust_price or index != times - 1:
                    continue

                if current["cover_order_status"] == "open":
                    if not self.cancel_order(rec["stock_code"], order.order_id):
                        continue
                    try:
                        confirmed = self._query_persisted_order(current, "close")
                        self._apply_order_report(rec["id"], "close", confirmed, rec.get("cover_client_order_id"), rec.get("cover_attempt"))
                    except CChanException as exc:
                        if exc.errcode == ErrCode.LIST_ORDER_FAIL:
                            continue
                        raise
                current = self.chan_db.get_record(rec["id"])
                if (current["cover_order_status"] in {"closed", "canceled", "rejected"} and current["status"] == "open"
                        and current.get("cover_client_order_id") == rec.get("cover_client_order_id")
                        and current.get("cover_attempt") == rec.get("cover_attempt")):
                    self.cover_trade(
                        current,
                        None,
                        current.get("cover_reason") or "retrade",
                    )
            if index != times - 1 and interval > 0:
                time.sleep(interval)

    def restore(self) -> List[dict]:
        """按订单号或客户端订单号核对在途订单，不进行猜测性重下。"""
        restored = []
        for rec in self.chan_db.get_recoverable_records():
            phase = "close" if rec["status"] == "closing" else "open"
            try:
                order = self._query_persisted_order(rec, phase)
                prefix = "open" if phase == "open" else "cover"
                self._apply_order_report(rec["id"], phase, order, rec.get(f"{prefix}_client_order_id"), rec.get(f"{prefix}_attempt"))
            except CChanException as exc:
                if exc.errcode == ErrCode.LIST_ORDER_FAIL:
                    continue
                raise
            restored.append(self.chan_db.get_record(rec["id"]))
        return restored
