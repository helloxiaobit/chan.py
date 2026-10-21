"""显式版本的真实结构导出，不运行经济研究或网络服务。"""
import copy
import hashlib
import json

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Decision import canonical_bytes, read_decision
from .test_decision_snapshots import CDecisionStrategy, HOUR, START
from .test_multilv import gen_15m_bars, aggregate


SOURCE = dict(exchange="binance", market_type="swap", settle="USDT", price_type="contract")
CODE = "TEST/USDT:USDT"
KINDS = {"klu", "klc", "bi", "seg", "segseg", "zs", "segzs", "bsp", "segbsp", "cbsp", "decisions"}


def single(n=3, *, source=SOURCE):
    chan = CChan(CODE, lv_list=[KL_TYPE.K_60M], config=CChanConfig({"trigger_step": True,
        "cbsp_strategy": CDecisionStrategy, "strategy_para": {"skip_features": True}}))
    for at in range(n):
        row = make_crypto_klu([START+at*HOUR, 100, 110, 90, 100+at, 2], KL_TYPE.K_60M)
        row.source_identity = source
        chan.trigger_load({KL_TYPE.K_60M: [row]})
    return chan


def payload(chan):
    result = chan.toJson(schema_version=2)
    assert result["schema"] == "chan-api-v2" and result["schema_version"] == 2
    assert set(result) == {"schema", "schema_version", "payload", "payload_sha256"}
    assert result["payload_sha256"] == hashlib.sha256(canonical_bytes(result["payload"])).hexdigest()
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    return result["payload"]


def test_default_legacy_shape_is_preserved_with_an_explicit_version_alias():
    chan = single()
    old = chan.toJson()
    assert set(old) == {"K_60M"}
    assert set(old["K_60M"]) == {"klu", "bi", "seg", "zs", "bsp", "cbsp"}
    assert chan.toJson(schema_version=1) == old
    assert old["K_60M"]["klu"][0] == dict(idx=0, time=chan[0][0][0].time.to_str(), open=100.0, high=110.0, low=90.0, close=100.0)


def test_v2_declares_current_view_separate_from_the_complete_original_decision_ledger():
    chan = single()
    result = payload(chan)
    assert result["code"] == CODE and result["level_order"] == ["K_60M"]
    assert result["structure_semantics"] == "current_view_not_historical_publication"
    level = result["levels"]["K_60M"]
    assert KINDS <= set(level)
    assert level["source"] == SOURCE and level["source_status"] == "known"
    assert level["observed_through_ms"] == START+3*HOUR
    raw = chan[0].cbsp_strategy.decision_records
    assert len(level["decisions"]) == len(raw) > 0
    for index, (event, original) in enumerate(zip(level["decisions"], raw)):
        assert event["ordinal"] == index
        assert event["record"] == read_decision(original)
        assert event["available_at_ms"] == event["record"]["identity"]["decision_ms"]
        assert event["time_basis"] == "utc_closed_bar"
    bar = level["klu"][0]
    assert bar["clock"] == dict(time_basis="utc_closed_bar", open_ms=START, close_ms=START+HOUR,
        available_at_ms=START+HOUR, is_final=True)
    assert bar["trade_info"]["volume"] == 2 and bar["source"] == SOURCE
    assert len(level["cbsp"]) == len(chan[0].cbsp_strategy)
    assert level["cbsp"][0]["open_event_id"] == read_decision(raw[0])["event_id"]
    assert level["cbsp"][0]["close_event_ids"]


@pytest.mark.parametrize("version", [1, 2])
def test_nonfinite_public_numbers_are_rejected_not_encoded_as_nan_or_strings(version):
    chan = single()
    chan[0][-1][-1].close = float("nan")
    with pytest.raises(CChanException):
        chan.toJson(schema_version=version)


def test_default_legacy_call_also_refuses_nonfinite_output():
    chan = single()
    chan[0][-1][-1].close = float("inf")
    with pytest.raises(CChanException):
        chan.toJson()


@pytest.mark.parametrize("version", [0, 3, True, "2", None])
def test_unknown_schema_versions_never_silently_fall_back(version):
    with pytest.raises(CChanException):
        single().toJson(schema_version=version)


def test_api_data_is_owned_and_original_events_never_follow_mutable_cbsp_changes():
    chan = single(1)
    first = payload(chan)
    original = copy.deepcopy(first)
    first["levels"]["K_60M"]["klu"][0]["close"] = -1
    first["levels"]["K_60M"]["decisions"][0]["record"]["payload"]["features"]["known"] = -1
    assert payload(chan) == original
    chan[0].cbsp_strategy[0].features.add_feat({"known": 999})
    changed = payload(chan)
    assert changed["levels"]["K_60M"]["decisions"] == original["levels"]["K_60M"]["decisions"]
    row = make_crypto_klu([START+HOUR, 100, 110, 90, 101, 2], KL_TYPE.K_60M)
    row.source_identity = SOURCE
    chan.trigger_load({KL_TYPE.K_60M: [row]})
    assert len(original["levels"]["K_60M"]["klu"]) == 1
    assert payload(chan)["levels"]["K_60M"]["decisions"][:1] == original["levels"]["K_60M"]["decisions"]


@pytest.mark.parametrize("bad", ["duplicate", "reverse", "foreign_code", "missing_parent"])
def test_export_does_not_trust_a_damaged_private_event_list(bad):
    from CustomBuySellPoint.Decision import make_decision
    chan = single()
    strategy = chan[0].cbsp_strategy
    records = list(strategy.decision_records)
    if bad == "duplicate":
        records.append(records[0])
    elif bad == "reverse":
        records.reverse()
    elif bad == "foreign_code":
        first = read_decision(records[0])
        first["identity"]["code"] = "OTHER/USDT:USDT"
        records[0] = make_decision(first["identity"], first["payload"])
    else:
        records = records[1:]
    strategy._decision_records = records
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


def test_real_structures_have_relationships_but_never_invent_confirmation_times():
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy
    chan = CChan(CODE, lv_list=[KL_TYPE.K_15M], config=CChanConfig({"trigger_step": True,
        "cbsp_strategy": CCustomStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
        "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": False, "strategy_para": {"skip_features": True}}))
    for row in gen_15m_bars(100):
        unit = make_crypto_klu(row, KL_TYPE.K_15M)
        unit.source_identity = SOURCE
        chan.trigger_load({KL_TYPE.K_15M: [unit]})
    view = payload(chan)["levels"]["K_15M"]
    for name, actual in (("klc", chan[0].lst), ("bi", chan[0].bi_list), ("seg", chan[0].seg_list),
        ("segseg", chan[0].segseg_list), ("zs", chan[0].zs_list), ("segzs", chan[0].segzs_list),
        ("bsp", chan[0].bs_point_lst.getSortedBspList()), ("segbsp", chan[0].seg_bs_point_lst.getSortedBspList())):
        assert len(view[name]) == len(list(actual))
        for item in view[name]:
            assert item["available_at_ms"] is None and item["availability"] == "not_recorded"
            assert len(item["snapshot_id"]) == 64 and "event_id" not in item
    assert len(view["bi"]) > 5 and len(view["seg"]) > 0 and len(view["zs"]) > 0
    for item, bi in zip(view["bi"], chan[0].bi_list):
        assert (item["begin_klu_idx"], item["end_klu_idx"], item["begin_val"], item["end_val"], item["is_sure"]) == (
            bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.get_begin_val(), bi.get_end_val(), bi.is_sure)


@pytest.mark.parametrize("damage", ["source", "close", "missing_clock", "nonfinite_feature"])
def test_bad_current_source_clock_or_feature_is_not_silently_removed(damage):
    chan = single()
    if damage == "source":
        chan[0][-1][-1].source_identity = {**SOURCE, "exchange": "okx"}
    elif damage == "close":
        chan[0][-1][-1].close_ms += 1
    elif damage == "missing_clock":
        del chan[0][-1][-1].available_at_ms
    else:
        chan[0].cbsp_strategy[0].features.add_feat({"invalid": float("inf")})
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


def test_partial_and_unknown_sources_are_disclosed_without_guessing_a_venue():
    chan = single()
    del chan[0][0][0].source_identity
    level = payload(chan)["levels"]["K_60M"]
    assert level["source_status"] == "partial" and level["source"] is None
    for unit in chan[0].klu_iter():
        if hasattr(unit, "source_identity"):
            del unit.source_identity
    assert payload(chan)["levels"]["K_60M"]["source_status"] == "unknown"


def test_legacy_unspecified_clock_remains_unknown_and_does_not_claim_utc_availability():
    from .test_decision_snapshots import channel
    from .conftest import make_klu
    chan = channel()
    chan.trigger_load({KL_TYPE.K_60M: [make_klu(dict(year=2024, month=1, day=1, open=100, high=110, low=90, close=100, volume=1))]})
    level = payload(chan)["levels"]["K_60M"]
    assert level["source_status"] == "unknown" and level["observed_through_ms"] is None
    assert level["klu"][0]["clock"] == dict(time_basis="legacy_unspecified", open_ms=None,
        close_ms=None, available_at_ms=None, is_final=None)
    assert level["decisions"][0]["available_at_ms"] is None


def test_nonfinal_current_bar_cannot_be_reported_as_confirmed_even_after_external_mutation():
    chan = single()
    chan[0][-1][-1].is_final = False
    level = payload(chan)["levels"]["K_60M"]
    assert level["observed_through_ms"] is None
    assert level["klu"][-1]["clock"]["is_final"] is False
    assert level["klu"][-1]["clock"]["available_at_ms"] is None


@pytest.mark.parametrize("damage", ["exit_direction", "event_clock", "event_source", "open_link", "close_link"])
def test_rehashed_event_or_cbsp_link_still_needs_its_real_published_context(damage):
    from CustomBuySellPoint.Decision import make_decision
    chan = single()
    strategy = chan[0].cbsp_strategy
    records = list(strategy.decision_records)
    exit_index = next(i for i, raw in enumerate(records) if read_decision(raw)["identity"]["kind"] == "exit")
    event = read_decision(records[exit_index])
    if damage == "exit_direction":
        event["identity"]["is_buy"] = not event["identity"]["is_buy"]
        records[exit_index] = make_decision(event["identity"], event["payload"])
    elif damage == "event_clock":
        event["payload"]["bar"]["open_ms"] += 1
        records[exit_index] = make_decision(event["identity"], event["payload"])
    elif damage == "event_source":
        event["payload"]["bar"]["market"] = {**SOURCE, "exchange": "okx"}
        records[exit_index] = make_decision(event["identity"], event["payload"])
    elif damage == "open_link":
        strategy[0]._open_decision = records[-1]
    else:
        strategy[0].close_actions[0]._decision = records[0]
    strategy._decision_records = records
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


def test_empty_channel_has_explicit_empty_levels_not_a_fake_observation_time():
    chan = CChan(CODE, lv_list=[KL_TYPE.K_4H, KL_TYPE.K_60M, KL_TYPE.K_15M], config=CChanConfig({"trigger_step": True}))
    result = payload(chan)
    assert result["level_order"] == ["K_4H", "K_60M", "K_15M"]
    for level in result["levels"].values():
        assert level["source_status"] == "unknown" and level["observed_through_ms"] is None
        assert all(level[kind] == [] for kind in KINDS)


def test_same_symbol_shape_on_another_venue_cannot_share_a_snapshot_identity():
    first = payload(single())["levels"]["K_60M"]
    other = payload(single(source={**SOURCE, "exchange": "okx"}))["levels"]["K_60M"]
    assert first["klc"][0]["snapshot_id"] != other["klc"][0]["snapshot_id"]


@pytest.mark.parametrize("damage", ["partial_event_clock", "orphan_parent", "invalid_index"])
def test_malformed_references_and_incomplete_event_clocks_fail_closed(damage):
    from CustomBuySellPoint.Decision import make_decision
    chan = single()
    if damage == "partial_event_clock":
        chan[0].cbsp_strategy.publish_signals(chan, 0)
        records = list(chan[0].cbsp_strategy.decision_records)
        event = read_decision(records[-1])
        del event["payload"]["bar"]["available_at_ms"]
        records[-1] = make_decision(event["identity"], event["payload"])
        chan[0].cbsp_strategy._decision_records = records
    elif damage == "orphan_parent":
        foreign = make_crypto_klu([START+12*HOUR, 100, 110, 90, 100, 1], KL_TYPE.K_4H)
        # The deliberately foreign reference is not an input row or valid venue data.
        foreign.set_idx(999)
        foreign.kl_type = KL_TYPE.K_4H
        chan[0][0][0].sup_kl = foreign
    else:
        chan[0][0][0].set_idx(True)
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


def test_three_level_load_and_online_feed_export_identical_complete_payloads(monkeypatch):
    from Common.CEnum import AUTYPE
    from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
    from .test_multilv import LV_LIST, BASE_CONF
    bars = gen_15m_bars(80)
    rows = {KL_TYPE.K_4H: aggregate(bars, 16), KL_TYPE.K_60M: aggregate(bars, 4), KL_TYPE.K_15M: bars}
    def unit(row, level):
        result = make_crypto_klu(row, level)
        result.source_identity = SOURCE
        return result
    class CFixtureAPI:
        def __init__(self, code, k_type, **kwargs):
            self.level = k_type
        @classmethod
        def do_init(cls):
            pass
        @classmethod
        def do_close(cls):
            pass
        def get_kl_data(self):
            yield from (unit(row, self.level) for row in rows[self.level])
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CFixtureAPI)
    config = {**BASE_CONF, "cbsp_strategy": CMultiLevelStrategy, "cal_feature": True,
        "strategy_para": {"require_sub_confirm": False}}
    loaded = CChan(CODE, lv_list=LV_LIST, config=CChanConfig(copy.deepcopy(config)), autype=AUTYPE.NONE)
    online = CChan(CODE, lv_list=LV_LIST, config=CChanConfig({**config, "trigger_step": True}), autype=AUTYPE.NONE)
    online.trigger_load({level: [unit(row, level) for row in rows[level][:16//group]]
        for level, group in ((KL_TYPE.K_4H, 16), (KL_TYPE.K_60M, 4), (KL_TYPE.K_15M, 1))})
    for index in range(16, len(bars)):
        row = bars[index]
        batch = {KL_TYPE.K_4H: [], KL_TYPE.K_15M: [unit(row, KL_TYPE.K_15M)]}
        if (index+1) % 4 == 0:
            batch[KL_TYPE.K_60M] = [unit(rows[KL_TYPE.K_60M][index//4], KL_TYPE.K_60M)]
        if (index+1) % 16 == 0:
            batch[KL_TYPE.K_4H] = [unit(rows[KL_TYPE.K_4H][index//16], KL_TYPE.K_4H)]
        online.trigger_load(batch)
    expected, actual = payload(loaded), payload(online)
    assert canonical_bytes(expected) == canonical_bytes(actual)
    assert sum(len(view["decisions"]) for view in actual["levels"].values()) > 10
    for name in actual["level_order"]:
        view = actual["levels"][name]
        for bar in view["klu"]:
            if bar["parent"]:
                parent = actual["levels"][bar["parent"]["level"]]["klu"][bar["parent"]["klu_idx"]]
                assert {"level": name, "klu_idx": bar["idx"]} in parent["children"]


def test_different_known_venues_across_levels_are_not_a_single_market_view():
    chan = CChan(CODE, lv_list=[KL_TYPE.K_4H, KL_TYPE.K_60M], config=CChanConfig({"trigger_step": True}))
    parent = make_crypto_klu([START, 100, 110, 90, 100, 4], KL_TYPE.K_4H)
    parent.source_identity = SOURCE
    children = [make_crypto_klu([START+n*HOUR, 100, 110, 90, 100, 1], KL_TYPE.K_60M) for n in range(4)]
    for child in children:
        child.source_identity = {**SOURCE, "exchange": "okx"}
    chan.trigger_load({KL_TYPE.K_4H: [parent], KL_TYPE.K_60M: children})
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


def test_original_event_market_must_not_be_relabelled_by_the_current_view():
    chan = single()
    for unit in chan[0].klu_iter():
        unit.source_identity = {**SOURCE, "exchange": "okx"}
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)


@pytest.mark.parametrize("damage", ["container", "container_index", "unaligned_clock"])
def test_bad_containment_and_unaligned_utc_clock_cannot_look_like_valid_data(damage):
    from Common.CTime import CTime
    from datetime import datetime, timezone
    chan = CChan(CODE, lv_list=[KL_TYPE.K_60M], config=CChanConfig({"trigger_step": True}))
    units = [make_crypto_klu([START+n*HOUR, 100+n*100, 110+n*100, 90+n*100, 100+n*100, 1], KL_TYPE.K_60M)
        for n in range(2)]
    chan.trigger_load({KL_TYPE.K_60M: units})
    if damage == "container":
        units[0].set_klc(units[1].klc)
    elif damage == "container_index":
        units[0].klc.idx = True
    else:
        for key in ("open_ms", "close_ms", "available_at_ms"):
            setattr(units[0], key, getattr(units[0], key)+1000)
        dt = datetime.fromtimestamp(units[0].close_ms/1000, tz=timezone.utc)
        units[0].time = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, auto=False, tzinfo=timezone.utc)
    with pytest.raises(CChanException):
        chan.toJson(schema_version=2)
