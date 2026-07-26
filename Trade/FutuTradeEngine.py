"""futu 交易引擎(可选件;需 pip install futu-api 并运行 FutuOpenD,不做测试要求)"""
from typing import Dict, Optional

from Common.ChanException import CChanException, ErrCode

from .db_util import CChanDB
from .OpenQuotaGen import COpenQuotaGen
from .TradeEngine import COrderResult, CTradeEngine


class CFutuTradeEngine(CTradeEngine):
    def __init__(self, market: str, chan_db: CChanDB, quota_gen: Optional[COpenQuotaGen] = None,
                 trd_env: str = "SIMULATE", push_msg: bool = True):
        super(CFutuTradeEngine, self).__init__(
            market=market, chan_db=chan_db, quota_gen=quota_gen, push_msg=push_msg)
        try:
            import futu as ft  # 懒加载,可选依赖
        except ImportError as e:
            raise CChanException(
                "futu 交易引擎需要 futu-api,请先 pip install futu-api 并启动 FutuOpenD;"
                "加密货币实盘请使用 CCCXTTradeEngine",
                ErrCode.PLACE_ORDER_FAIL,
            ) from e
        try:
            from Config.EnvConfig import CEnv
            futu_conf = CEnv.get_instance().futu_conf
        except Exception:
            futu_conf = {}
        self.ft = ft
        self.trd_env = ft.TrdEnv.SIMULATE if trd_env == "SIMULATE" else ft.TrdEnv.REAL
        _market_map = {"hk": ft.TrdMarket.HK, "us": ft.TrdMarket.US, "cn": ft.TrdMarket.CN}
        self.trd_ctx = ft.OpenSecTradeContext(
            filter_trdmarket=_market_map.get(market, ft.TrdMarket.HK),
            host=futu_conf.get("host", "127.0.0.1"),
            port=int(futu_conf.get("port", 11111)),
        )

    def place_order(self, code: str, is_buy: bool, amount: float, price: Optional[float] = None) -> COrderResult:
        ft = self.ft
        ret, data = self.trd_ctx.place_order(
            price=price or 0,
            qty=amount,
            code=code,
            trd_side=ft.TrdSide.BUY if is_buy else ft.TrdSide.SELL,
            order_type=ft.OrderType.NORMAL if price is not None else ft.OrderType.MARKET,
            trd_env=self.trd_env,
        )
        if ret != ft.RET_OK:
            raise CChanException(f"futu 下单失败: {data}", ErrCode.PLACE_ORDER_FAIL)
        row = data.iloc[0]
        return COrderResult(str(row["order_id"]), float(row.get("dealt_qty", 0) or 0), None, "open")

    def cancel_order(self, code: str, order_id: str) -> bool:
        ft = self.ft
        ret, data = self.trd_ctx.modify_order(ft.ModifyOrderOp.CANCEL, order_id, 0, 0, trd_env=self.trd_env)
        if ret != ft.RET_OK:
            raise CChanException(f"futu 撤单失败: {data}", ErrCode.CANDEL_ORDER_FAIL)
        return True

    def query_order(self, code: str, order_id: str) -> COrderResult:
        ft = self.ft
        ret, data = self.trd_ctx.order_list_query(order_id=order_id, trd_env=self.trd_env)
        if ret != ft.RET_OK or len(data) == 0:
            raise CChanException(f"futu 查单失败: {data}", ErrCode.LIST_ORDER_FAIL)
        row = data.iloc[0]
        status_map = {"FILLED_ALL": "closed", "CANCELLED_ALL": "canceled"}
        return COrderResult(
            str(row["order_id"]), float(row.get("dealt_qty", 0) or 0),
            float(row["dealt_avg_price"]) if row.get("dealt_avg_price") else None,
            status_map.get(str(row["order_status"]), "open"),
        )

    def get_balance(self) -> Dict[str, float]:
        ft = self.ft
        ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
        if ret != ft.RET_OK:
            raise CChanException(f"futu 查资金失败: {data}", ErrCode.GET_HOLDING_QTY_FAIL)
        return {"cash": float(data.iloc[0]["cash"])}

    def get_position(self, code: str) -> float:
        ft = self.ft
        ret, data = self.trd_ctx.position_list_query(code=code, trd_env=self.trd_env)
        if ret != ft.RET_OK:
            raise CChanException(f"futu 查持仓失败: {data}", ErrCode.GET_HOLDING_QTY_FAIL)
        return float(data.iloc[0]["qty"]) if len(data) else 0.0

    def close(self):
        self.trd_ctx.close()
