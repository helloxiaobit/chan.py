import json

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.candidate import load_candidate_dataset
from ModelStrategy.research.provenance import canonical_json_bytes


def candidate_payload(**overrides):
    trade = {
        "entry_ts": parse_utc("2021-02-01"),
        "close_ts": parse_utc("2021-02-02"),
        "open_price": 100.0,
        "close_price": 105.0,
        "risk_rate": 0.05,
        "bs_type": "z1",
        "is_buy": True,
        "is_pyramid": False,
        "reason": "trend_flip",
        "is_closed": True,
    }
    payload = {
        "schema_version": 2,
        "entry_kind": "strategy_fill",
        "symbol": "BTC/USDT",
        "stack": "S1bz[4H,1H,15M]",
        "source": {
            "path": "BTC_S1bz_2125.pkl",
            "size": 123,
            "sha256": "a" * 64,
            "timestamp_offset_seconds": 0,
            "raw_entry_ts_min": parse_utc("2021-02-01"),
            "raw_close_ts_max": parse_utc("2021-02-02"),
            "corrected_entry_ts_min": parse_utc("2021-02-01"),
            "corrected_close_ts_max": parse_utc("2021-02-02"),
        },
        "trades": [trade],
    }
    payload.update(overrides)
    return payload


def write_payload(tmp_path, payload):
    path = tmp_path / "candidate.json"
    path.write_bytes(canonical_json_bytes(payload))
    return path


def test_candidate_dataset_loads_portable_price_bearing_records(tmp_path):
    dataset = load_candidate_dataset(
        write_payload(tmp_path, candidate_payload())
    )
    assert dataset.entry_kind == "strategy_fill"
    assert dataset.symbol == "BTC/USDT"
    assert dataset.stack == "S1bz[4H,1H,15M]"
    assert dataset.source.sha256 == "a" * 64
    assert dataset.source.timestamp_offset_seconds == 0
    assert dataset.trades[0].open_price == 100.0
    assert dataset.trades[0].reason == "trend_flip"


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update({"unexpected": True}), "keys"),
        (
            lambda value: value.update({"entry_kind": "implicit_fill"}),
            "entry_kind",
        ),
        (
            lambda value: value["trades"][0].update({"open_price": 0}),
            "open_price",
        ),
        (
            lambda value: value["trades"][0].pop("is_pyramid"),
            "keys",
        ),
        (
            lambda value: value["source"].update(
                {"timestamp_offset_seconds": 0.5}
            ),
            "timestamp_offset_seconds",
        ),
        (
            lambda value: value["source"].update(
                {
                    "corrected_entry_ts_min": parse_utc("2021-02-01")
                    + 1
                }
            ),
            "corrected",
        ),
    ],
)
def test_candidate_dataset_rejects_ambiguous_or_extra_fields(
    tmp_path, mutation, match
):
    payload = candidate_payload()
    mutation(payload)
    with pytest.raises(ValueError, match=match):
        load_candidate_dataset(write_payload(tmp_path, payload))


def test_candidate_dataset_rejects_oos_before_opening_a_gate(tmp_path):
    payload = candidate_payload()
    payload["trades"][0]["close_ts"] = parse_utc("2026-01-01")
    with pytest.raises(ValueError, match="OOS"):
        load_candidate_dataset(write_payload(tmp_path, payload))


def test_candidate_dataset_requires_envelope_identity_to_match(tmp_path):
    payload = candidate_payload(symbol="ETH/USDT")
    dataset = load_candidate_dataset(
        write_payload(tmp_path, payload),
        expected_symbol="ETH/USDT",
        expected_stack="S1bz[4H,1H,15M]",
        expected_entry_kind="strategy_fill",
    )
    assert dataset.symbol == "ETH/USDT"
    with pytest.raises(ValueError, match="symbol"):
        load_candidate_dataset(
            write_payload(tmp_path, payload), expected_symbol="BTC/USDT"
        )


def test_candidate_json_must_be_an_object(tmp_path):
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        load_candidate_dataset(path)
