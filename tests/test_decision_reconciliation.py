"""C2 完整身份、顺序与内容校验；两边同错也必须被内部约束拒绝。"""
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import make_decision, read_decision
from ModelStrategy import FeatureReconciliation as reconcile
from .test_decision_snapshots import channel, feed


def records():
    chan = channel()
    for n in range(3):
        feed(chan, n)
    strategy = chan[0].cbsp_strategy
    strategy.publish_signals(chan, 0)
    return list(strategy.decision_records)


def compare(left, right, **kwargs):
    return reconcile.reconcile_decision_records(left, right, **kwargs)


def kinds(report):
    return {item["type"] for item in report.mismatches}


def changed(raw, path, value):
    item = read_decision(raw)
    obj = item["payload"]
    for part in path[:-1]:
        obj = obj[part]
    obj[path[-1]] = value
    return make_decision(item["identity"], item["payload"])


def test_identical_canonical_decisions_have_exact_coverage_counts():
    source = records()
    report = compare(source, source)
    assert report.is_consistent and report.is_exact
    assert report.event_cnt_offline == report.event_cnt_online == 5
    assert report.cbsp_cnt_offline == report.cbsp_cnt_online == 2


@pytest.mark.parametrize("idx,path,value", [
    (0, ["features", "known"], 101.0),
    (0, ["score"], 0.1),
    (0, ["sl_price"], 94),
    (0, ["open_price"], 99),
    (0, ["dedupe", "opened_bsp_klu_idx"], [99]),
    (1, ["price"], 102),
    (1, ["quota"], 0.25),
    (1, ["reason"], "wrong_exit"),
    (4, ["open_thred"], 106),
    (4, ["score"], 0.5),
])
def test_one_field_mutation_reports_the_exact_payload_path(idx, path, value):
    baseline = records()
    actual = list(baseline)
    actual[idx] = changed(actual[idx], path, value)
    report = compare(baseline, actual)
    assert not report.is_consistent and not report.is_exact
    assert report.mismatches == [{"type": "payload_mismatch", "event_id": read_decision(baseline[idx])["event_id"],
                                   "path": ["payload", *path]}]


def test_missing_extra_and_duplicate_records_are_not_hidden_by_zip():
    baseline = records()
    assert "missing_event" in kinds(compare(baseline, baseline[1:]))
    assert "extra_event" in kinds(compare(baseline[1:], baseline))
    assert "duplicate_event" in kinds(compare(baseline, [*baseline, baseline[-1]]))


def test_same_timestamp_reordering_is_a_difference_even_with_identical_sets():
    baseline = records()
    assert read_decision(baseline[2])["identity"]["decision_ms"] == read_decision(baseline[3])["identity"]["decision_ms"]
    actual = [*baseline[:2], baseline[3], baseline[2], baseline[4]]
    assert "event_order" in kinds(compare(baseline, actual))


def test_two_lanes_with_the_same_invalid_dependency_do_not_self_certify():
    source = records()[1:]  # 两边都漏开仓，不能用 expected=actual 自证。
    report = compare(source, source)
    assert not report.is_consistent and not report.is_exact
    assert "invalid_parent" in kinds(report)


def test_two_lanes_with_the_same_skipped_exit_sequence_do_not_self_certify():
    baseline = records()
    actual = [baseline[0], *baseline[2:]]  # 首次出现的退出序号为 1。
    report = compare(actual, actual)
    assert not report.is_consistent
    assert "exit_sequence" in kinds(report)


def test_noncanonical_or_nonfinite_data_is_rejected_even_if_both_lanes_match():
    raw = records()[0]
    for invalid in (raw + b"\n", b"{broken", raw.replace(b'100.0', b'NaN', 1)):
        report = compare([invalid], [invalid])
        assert not report.is_consistent and not report.is_exact
        assert "invalid_record" in kinds(report)


def test_time_reversal_is_reported_independently_of_lane_equality():
    baseline = records()
    source = [baseline[1], baseline[0], *baseline[2:]]
    assert "non_monotonic" in kinds(compare(source, source))


def test_default_is_exact_and_explicit_feature_tolerance_cannot_claim_exactness():
    baseline = records()
    actual = [changed(baseline[0], ["features", "known"], 100.0 + 1e-10), *baseline[1:]]
    assert not compare(baseline, actual).is_consistent
    report = compare(baseline, actual, rel_tol=1e-8)
    assert report.is_consistent
    assert not report.is_exact


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_tolerance_is_not_a_way_to_suppress_drift(value):
    with pytest.raises(CChanException):
        compare(records(), records(), rel_tol=value)
