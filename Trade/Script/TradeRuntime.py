"""One configured engine lifetime for entry and original-order management scripts."""
from contextlib import contextmanager

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from Config.EnvConfig import CEnv


@contextmanager
def configured_trade_engine(db, *, env=None, quota_gen=None, opening_inputs=None, now_ms=None, push_msg=True):
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.PaperState import CPersistentPaperState
    from Trade.PaperInputs import CSoftwarePaperInputs
    env = env or CEnv.get_instance()
    trade, ccxt = env.get_section("trade"), env.ccxt_conf
    options = dict(quota_gen=quota_gen, ccxt_conf=ccxt, trade_conf=trade, opening_inputs=opening_inputs, push_msg=push_msg)
    if "paper" not in trade:
        yield CCCXTTradeEngine(db, **options)
        return
    profile = trade["paper"]
    if (not isinstance(profile, dict) or set(profile) != {"server_path", "quote_path", "quote_max_age_ms"}
            or any(not isinstance(profile[k], str) or not profile[k] for k in ("server_path", "quote_path"))
            or ccxt.get("mode") != "dry_run" or ccxt.get("default_type") != "swap" or db.db_type != "sqlite"):
        raise CChanException("显式 paper profile 需要原 SQLite/server 与软件行情，不能回退或用于真实交易", ErrCode.TRADE_UNLOCK_FAIL)
    inputs = CSoftwarePaperInputs(env.abs_path(profile["quote_path"]), source=env.offline_data_conf.get("source_identity"),
        max_age_ms=profile["quote_max_age_ms"], now_ms=now_ms or utc_now_ms)
    if inputs.source["exchange"] != ccxt.get("exchange"):
        raise CChanException("paper 配置 venue 与明确软件行情来源不一致", ErrCode.TRADE_UNLOCK_FAIL)
    database = next(row["file"] for row in db.db.query("PRAGMA database_list") if row["name"] == "main")
    with CPersistentPaperState.open(env.abs_path(profile["server_path"]), database=database) as server:
        engine = CCCXTTradeEngine(db, sim_state=server.state, paper_inputs=inputs, **options)
        try:
            inputs.prime(engine)
        except CChanException:
            # Preserve access to original known reports/cancellation. Missing
            # quotes never create fills or a replacement funded account.
            pass
        yield engine
