"""Signal expiry respects the original opportunity key and actual scan scope."""
import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
from Common.KLineTime import make_crypto_klu
from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from CustomBuySellPoint.Signal import CSignal
from Trade.db_util import CChanDB
from Trade.Script import SignalMonitor as monitor
from .test_decision_snapshots import CDecisionStrategy, START, HOUR

CODE = "BTC/USDT:USDT"
SOURCE = {"exchange": "binance", "market_type": "swap", "settle": "USDT", "price_type": "contract"}


def signal(level, *, is_buy=True, at=START):
    unit = make_crypto_klu([at, 100, 110, 90, 100, 1], level)
    unit.source_identity = SOURCE
    value = CSignal(CODE, level, is_buy, "watch", unit, 105 if is_buy else 95,
        sl_thred=95 if is_buy else 105, target_klu_time=unit.time, score=0.75)
    value.freeze_decision()
    return value


@pytest.fixture()
def scope(tmp_path, monkeypatch):
    config = tmp_path/"runtime.json"
    config.write_bytes(canonical_bytes({"trade": {"code_list": [CODE], "lv": "K_60M"},
        "notify": {"backend": "none"}}))
    monkeypatch.setenv("CHANPY_CONFIG", str(config))
    CEnv.reset_instance()
    current = {"is_buy": False, "empty": False, "both": False}

    class CSyntheticScopeStrategy(CDecisionStrategy):
        def bsp_signal(self, chan, lv):
            if current["empty"]:
                return []
            cur = chan[lv][-1][-1]
            directions = [True, False] if current["both"] else [current["is_buy"]]
            return [CSignal(chan.code, chan.lv_list[lv], buy, "watch", cur, 105 if buy else 95,
                sl_thred=95 if buy else 105, target_klu_time=cur.time, score=0.75) for buy in directions]

    chan = CChan(CODE, lv_list=[KL_TYPE.K_60M], config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": CSyntheticScopeStrategy, "strategy_para": {"skip_features": True}}))
    unit = make_crypto_klu([START, 100, 110, 90, 100, 1], KL_TYPE.K_60M, START+HOUR)
    unit.source_identity = SOURCE
    chan.trigger_load({KL_TYPE.K_60M: [unit]})
    # Replace only the data-source construction with a real closed-bar channel;
    # publication, original signal bytes, SQLite and expiry all run unchanged.
    monkeypatch.setattr(monitor, "CChan", lambda **kwargs: chan)
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")})
    try:
        yield db, current
    finally:
        db.close()
        CEnv.reset_instance()


def run(db):
    return monitor.run_signal_monitor(db, code_list=[CODE], lv_list=[KL_TYPE.K_60M], push=False)


def test_opposite_direction_at_the_same_target_expires_only_the_old_opportunity(scope):
    db, _ = scope
    old = signal(KL_TYPE.K_60M)
    key = db.add_signal(old)
    result = run(db)
    row = db.get_record(key)
    assert row["watching"] == 0, "a new short at the same target must not keep the old long eligible"
    assert row["signal_decision"] == old.decision.decode() and row["unwatch_reason"] == "signal_expired"
    assert result == {"added": 1, "existed": 0, "unwatched": 1, "failed": 0}
    assert [bool(item["is_buy"]) for item in db.get_watching_signals(CODE)] == [False]


@pytest.mark.parametrize("empty", [False, True])
def test_scan_cannot_expire_a_level_it_did_not_observe(scope, empty):
    db, current = scope
    key = db.add_signal(signal(KL_TYPE.K_15M, at=START+900_000))
    before = db.get_record(key)
    current["empty"] = empty
    result = run(db)
    assert db.get_record(key) == before, "an hourly scan is not absence evidence for a 15m signal"
    assert result["unwatched"] == 0 and result["failed"] == 0


def test_rejected_signal_set_cannot_leave_a_half_accepted_candidate(scope):
    db, current = scope
    key = db.add_signal(signal(KL_TYPE.K_60M, is_buy=False))
    before = db.get_record(key)
    current["both"] = True  # first candidate is new; second conflicts with frozen original bytes
    result = run(db)
    assert result["failed"] == 1 and result["added"] == 0
    assert db.db.query(f"SELECT * FROM {db.table} ORDER BY id") == [before], "failed sets must roll back their new candidates"
