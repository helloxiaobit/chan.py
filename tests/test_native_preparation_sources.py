"""Actual Engine/native metadata and nonempty account components together."""
from decimal import Decimal
import json
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.NativeComponentCollector import collect_and_check_native_components
from Trade.NativeInstrumentCurrent import collect_native_instruments_for_engine
from Trade.NativeOrderBoundary import assert_native_order_boundary, capture_native_order_boundary
from Trade.NativePreparation import capture_native_prepare_identity
from .native_order_preparation_case import CODES, native_order_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment


def _observe_prerequisites(case):
    """Test-only manual composition, not the missing production CAS binding."""
    db = case["db"]
    identity = capture_native_prepare_identity(case["trade"], case["key"], .1, 100)
    instruments = collect_native_instruments_for_engine(case["trade"], CODES, max_age_ms=2000, max_observation_span_ms=2000)
    components = collect_and_check_native_components(db, case["client"], mode="testnet", markets=case["units"],
        before_id=case["before_id"], account_scope="native-preparation-fixture", policy=case["policy"])
    later = capture_native_prepare_identity(case["trade"], case["key"], .1, 100)
    assert identity["payload"]["order_contract"] == later["payload"]["order_contract"]
    p = components["payload"]
    boundary = capture_native_order_boundary(db, account_context=p["account_context"], check_id=p["check_id"],
                                            market_evidence=p["market_evidence"], policy=case["policy"])
    with db.db.transaction():
        assert_native_order_boundary(db, boundary)
    return identity, instruments, components


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(m, s) for m in ("one_way", "hedged") for s in (True, False)])
def test_real_native_units_nonempty_account_and_original_prepare_share_one_client(store, tmp_path, monkeypatch, venue, mode, side):
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue, mode=mode, side=side)
    native_before = case["before"]["payload"]["raw"]["account"]["assets" if venue == "binance" else "details"][0]
    assert Decimal(native_before["initialMargin" if venue == "binance" else "imr"]) == 0
    assert Decimal(native_before["availableBalance" if venue == "binance" else "availEq"]) == 1000
    if venue == "okx":
        assert Decimal(case["account_raw"]["upl"]) == Decimal(".8")
        assert Decimal(case["account_raw"]["totalEq"]) == Decimal("1000.969")
    before_orders = db.db.query("SELECT * FROM chan_trade")
    identity, instruments, components = _observe_prerequisites(case)
    p = components["payload"]
    check = db.get_account_check(p["check_id"])
    report = check["payload"]["report"]["payload"]
    assert report["status"] == "matched_observations", report
    prepared_market = identity["payload"]["order_contract"]["market"]
    assert Decimal(prepared_market["contractSize"]) == (Decimal("1") if venue == "binance" else Decimal("0.01"))
    assert prepared_market == next(row["market"] for row in instruments["payload"]["observations"] if row["market"]["symbol"] == CODES[0])
    assert len(instruments["payload"]["observations"]) == 2
    assert len(check["payload"]["inputs"]["after"]["payload"]["positions"]) == 2
    assert len(check["payload"]["inputs"]["histories"]) == 2
    economic = report["components"]["payload"]
    interval = economic["interval"]["payload"]
    assert interval["wallets"][0]["difference"] == {"numerator": "0", "denominator": "1"}
    primary = next(row for row in interval["positions"] if row["leg"][0] == CODES[0])
    assert primary["quantity"] == {"numerator": "1", "denominator": "25"}
    assert primary["unrealized_pnl"] == {"numerator": "4", "denominator": "5"}
    assert economic["margin"]["reported_available"] == "988.969"
    assert economic["margin"]["aggregate_order_margin"] == "10"
    assert len(economic["pending"]["payload"]["reservations"]) == 1
    assert all(db.get_record(key)["current_qty"] > 0 for key in case["history_keys"])
    assert len(case["created"]) == 3 and db.db.query("SELECT * FROM chan_trade") == before_orders
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert db.get_account_risk_state(p["account_context"])["frozen"] is False


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["instrument", "candidate", "pending", "wallet", "funding", "cash"])
def test_native_unit_joint_prerequisites_do_not_hide_a_changed_source(store, tmp_path, monkeypatch, venue, damage):
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue)
    before_orders = db.db.query("SELECT * FROM chan_trade")
    if damage == "instrument":
        cached = canonical_bytes(case["client"].markets)
        case["raw"][0]["status" if venue == "binance" else "state"] = "BREAK" if venue == "binance" else "suspend"
        assert canonical_bytes(case["client"].markets) == cached, "independent GET data must not mutate the initialized SDK cache"
    elif damage == "candidate":
        path = Path(case["trade"].safety_policy.strategy_receipt["path"])
        document = json.loads(path.read_bytes())
        document["status"] = "rejected"
        path.write_text(json.dumps(document), encoding="utf-8")
    elif damage == "pending":
        case["pending_raw"]["executedQty" if venue == "binance" else "accFillSz"] = ".4" if venue == "binance" else "4"
    elif damage == "wallet":
        case["wallet_io"].rows[0]["income" if venue == "binance" else "fee"] = "-.007"
    elif damage == "funding":
        raw = case["execution_io"][case["units"][0]["id"]].cash[0]
        raw["income" if venue == "binance" else "pnl"] = "-.03"
        if venue == "okx":
            raw["balChg"] = "-.03"
    else:
        raw = case["account_raw"]["assets" if venue == "binance" else "details"][0]
        raw["walletBalance" if venue == "binance" else "cashBal"] = "1001"
    with pytest.raises(CChanException):
        _observe_prerequisites(case)
    assert db.db.query("SELECT * FROM chan_trade") == before_orders
    if damage in {"pending", "wallet", "funding", "cash"}:
        context = case["before"]["payload"]["account_context"]
        assert db.get_account_risk_state(context)["frozen"] is True


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_candidate_changed_during_component_reads_is_not_validated_only_at_start(store, tmp_path, monkeypatch, venue):
    db, conf = store
    case = native_order_case(db, conf, tmp_path, monkeypatch, venue)
    method = "fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice"
    get = getattr(case["client"], method)
    def changed(params):
        result = get(params)
        path = Path(case["trade"].safety_policy.strategy_receipt["path"])
        document = json.loads(path.read_bytes())
        document["status"] = "rejected"
        path.write_text(json.dumps(document), encoding="utf-8")
        return result
    monkeypatch.setattr(case["client"], method, changed)
    before_orders = db.db.query("SELECT * FROM chan_trade")
    with pytest.raises(CChanException):
        _observe_prerequisites(case)
    assert db.db.query("SELECT * FROM chan_trade") == before_orders
