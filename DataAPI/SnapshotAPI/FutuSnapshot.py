"""futu 实时行情快照(港美股;可选依赖 pip install futu-api,需本地 FutuOpenD)"""
from typing import List

from .CommSnapshot import CCommSnapshot, T_SNAPSHOT_RES


class CFutuSnapshot(CCommSnapshot):
    @classmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        res: T_SNAPSHOT_RES = {code: None for code in code_list}
        try:
            import futu as ft  # 懒加载,可选依赖
        except ImportError:
            print("[CFutuSnapshot] 需要 futu-api,请先 pip install futu-api 并启动 FutuOpenD")
            return res
        try:
            from Config.EnvConfig import CEnv
            futu_conf = CEnv.get_instance().futu_conf
        except Exception:
            futu_conf = {}
        quote_ctx = ft.OpenQuoteContext(
            host=futu_conf.get("host", "127.0.0.1"), port=int(futu_conf.get("port", 11111)))
        try:
            ret, df = quote_ctx.get_market_snapshot(code_list)
            if ret != ft.RET_OK:
                print(f"[CFutuSnapshot] 快照获取失败: {df}")
                return res
            for _, row in df.iterrows():
                res[str(row["code"])] = cls.make_result({
                    "name": str(row.get("name", row["code"])),
                    "open": float(row["open_price"]),
                    "yesterdayClose": float(row["prev_close_price"]),
                    "price": float(row["last_price"]),
                    "high": float(row["high_price"]),
                    "low": float(row["low_price"]),
                }, return_klu)
        finally:
            quote_ctx.close()
        return res
