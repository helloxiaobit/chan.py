import json

import pytest

from ModelStrategy.research.boundary import ResearchBoundaryError
from ModelStrategy.research.schema import ResearchTrade, load_trades


VALID = {
    "open_ts": 1609459200.0,
    "close_ts": 1609462800.0,
    "profit_rate": 1.25,
    "risk_rate": 0.02,
    "bs_type": "1",
    "is_buy": True,
}


def test_trade_defaults_pyramid_and_round_trips():
    trade = ResearchTrade.from_mapping(VALID)
    assert trade.is_pyramid is False
    assert trade.to_mapping()["is_pyramid"] is False


def test_trade_rejects_non_positive_risk():
    with pytest.raises(ValueError, match="risk_rate"):
        ResearchTrade.from_mapping({**VALID, "risk_rate": 0})


def test_trade_rejects_close_before_open():
    with pytest.raises(ValueError, match="close_ts"):
        ResearchTrade.from_mapping({**VALID, "close_ts": VALID["open_ts"] - 1})


def test_load_trades_rejects_oos_record(tmp_path):
    path = tmp_path / "trades.json"
    path.write_text(
        json.dumps(
            [
                {
                    **VALID,
                    "open_ts": 1767225600.0,
                    "close_ts": 1767229200.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ResearchBoundaryError):
        load_trades(path, is_only=True)
