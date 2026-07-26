"""线上缠论计算配置(单一来源):信号计算/开仓校验/实时跟踪统一用这一份"""
from typing import Dict, List, Optional

from Common.CEnum import KL_TYPE


def get_strategy_cls(name: str):
    if name == "multi_lv":
        from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
        return CMultiLevelStrategy
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy
    return CCustomStrategy


def get_statics_chan_config(extra: Optional[Dict] = None) -> Dict:
    trade_conf = get_trade_conf()
    conf = {
        "trigger_step": False,
        "divergence_rate": float("inf"),
        "min_zs_cnt": 0,
        "bs_type": "1,2,3a,1p,2s,3b",
        "cbsp_strategy": get_strategy_cls(trade_conf["strategy"]),
        "strategy_para": {
            "strict_open": True,
            "use_qjt": True,
            "short_shelling": True,
            "judge_on_close": True,
        },
        "kl_data_check": False,
    }
    conf.update(extra or {})
    return conf


def get_trade_conf() -> Dict:
    # config.yaml trade 段:监控标的/级别(单级别 lv 或多级别 lv_list)/策略/单笔名义金额
    try:
        from Config.EnvConfig import CEnv
        conf = CEnv.get_instance().get_section("trade")
    except Exception:
        conf = {}
    if "lv_list" in conf:
        lv_list = [KL_TYPE[x] for x in conf["lv_list"]]
    else:
        lv_list = [KL_TYPE[conf.get("lv", "K_60M")]]
    return {
        "code_list": conf.get("code_list", ["BTC/USDT", "ETH/USDT"]),
        "lv": lv_list[0],  # 兼容旧调用
        "lv_list": lv_list,
        "trade_lv_idx": 1 if len(lv_list) >= 2 else 0,  # 多级别时交易发生在中周期
        "strategy": conf.get("strategy", "custom"),  # custom / multi_lv
        "bench_price": float(conf.get("bench_price", 1000.0)),
    }


def get_code_list() -> List[str]:
    return get_trade_conf()["code_list"]
