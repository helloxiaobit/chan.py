import os

import pytest

from Common.ChanException import CChanException
from Config.EnvConfig import CEnv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_PATH = os.path.join(ROOT, "Config", "config_demo.yaml")


def test_load_demo_config():
    env = CEnv(DEMO_PATH)
    assert env.get("db.type") == "sqlite"
    assert env.db_conf["type"] == "sqlite"
    assert env.ccxt_conf["exchange"] == "binance"
    assert env.snapshot_engine == "ccxt"
    assert isinstance(env.notify_conf, dict)


def test_get_default_value():
    env = CEnv(DEMO_PATH)
    assert env.get("not.exist.key", "fallback") == "fallback"
    assert env.get("db.not_exist") is None
    assert env.get_section("not_exist_section") == {}


def test_abs_path():
    env = CEnv(DEMO_PATH)
    p = env.abs_path("Trade/chan_trade.db")
    assert os.path.isabs(p)
    assert p.startswith(ROOT)


def test_missing_config_raises():
    with pytest.raises(CChanException):
        CEnv(os.path.join(ROOT, "Config", "not_exist.yaml"))


def test_singleton_and_reset():
    CEnv.reset_instance()
    a = CEnv.get_instance()
    b = CEnv.get_instance()
    assert a is b
    CEnv.reset_instance()
    assert CEnv.get_instance() is not a
    CEnv.reset_instance()
