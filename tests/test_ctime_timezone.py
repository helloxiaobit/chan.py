from datetime import datetime, timezone

from Common.CEnum import AUTYPE, KL_TYPE
from Common.CTime import CTime
from DataAPI.OfflineDataAPI import CStockFileReader
from DataAPI.ccxt import CCXT


def test_ctime_explicit_utc_is_host_timezone_independent():
    value = CTime(2024, 1, 2, 3, 4, auto=False, tzinfo=timezone.utc)
    assert value.ts == datetime(
        2024, 1, 2, 3, 4, tzinfo=timezone.utc
    ).timestamp()


def test_ctime_default_preserves_legacy_local_semantics():
    value = CTime(2024, 1, 2, 3, 4, auto=False)
    assert value.ts == datetime(2024, 1, 2, 3, 4).timestamp()


def test_offline_crypto_bar_end_epoch_is_utc():
    raw_start_ms = int(
        datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    reader = CStockFileReader(
        "BTC/USDT", KL_TYPE.K_60M, None, None, AUTYPE.NONE
    )
    klu = reader.make_klu(raw_start_ms, 100, 101, 99, 100, 1)
    assert klu.time.ts == raw_start_ms / 1000 + 3600


def test_ccxt_crypto_bar_epoch_is_utc():
    raw_start_ms = int(
        datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    reader = CCXT("BTC/USDT", KL_TYPE.K_60M, None, None, AUTYPE.NONE)
    klu = reader.make_klu([raw_start_ms, 100, 101, 99, 100, 1])
    assert klu.time.ts == raw_start_ms / 1000
