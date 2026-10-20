"""多窗口账户搜索的隔离/可追溯产物，只用固定小合成数据。"""
import json

import pytest

from Common.ChanException import CChanException
from ModelStrategy.parameterEvaluate.account_experiment import run_account_experiment, verify_account_experiment
from .test_crypto_evaluation_binding import raw_fixture, dataset, configuration
from .test_decision_snapshots import START, HOUR


def options():
    return {"search_window": (START, START+600*HOUR),
            "validation_windows": [(START+600*HOUR, START+800*HOUR), (START+800*HOUR, START+1000*HOUR)],
            "space": {"entry_notional": {"type": "choice", "choices": [10.0, 20.0]}},
            "objective": "total_return", "n_trials": 2, "algorithm": "grid", "seed": 7,
            "min_closed_positions": 1}


@pytest.mark.parametrize("bad", ["overlap", "backwards", "empty", "target", "unused_parameter", "zero_budget"])
def test_bad_experiment_spec_creates_no_run_directory(tmp_path, bad):
    source = dataset(*raw_fixture())
    opts = options()
    if bad == "overlap":
        opts["validation_windows"] = [(START+500*HOUR, START+800*HOUR)]
    elif bad == "backwards":
        opts["validation_windows"] = list(reversed(opts["validation_windows"]))
    elif bad == "empty":
        opts["validation_windows"] = []
    elif bad == "target":
        opts["objective"] = "whatever-happens-to-look-good"
    elif bad == "unused_parameter":
        opts["space"] = {"unread_parameter": {"type": "int", "low": 1, "high": 2}}
    else:
        opts["n_trials"] = 0
    with pytest.raises(CChanException):
        run_account_experiment(source, configuration(), output_dir=tmp_path / "run", **opts)
    assert list(tmp_path.iterdir()) == []


def test_real_account_search_validation_and_proposal_are_separate_replayable_artifacts(tmp_path):
    source = dataset(*raw_fixture())
    config = configuration()
    root = tmp_path / "run"
    report = run_account_experiment(source, config, output_dir=root, **options())
    assert set(p.name for p in root.iterdir()) == {"search.jsonl", "validation.json", "proposal.json", "receipt.json"}
    search = [json.loads(line) for line in (root / "search.jsonl").read_bytes().splitlines()]
    validation = json.loads((root / "validation.json").read_bytes())
    proposal = json.loads((root / "proposal.json").read_bytes())
    assert report["status"] == "offline_window_checks_passed" and report["candidate_authorized"] is False
    assert all(r["run"]["context"]["objective"] == "total_return" for r in search)
    assert all(r["eval"]["account"]["window"]["end_ms"] == START+600*HOUR for r in search)
    chosen = max(search, key=lambda r: r["score"])["para"]
    assert proposal["parameters"] == chosen and proposal["candidate_authorized"] is False
    assert [r["account"]["window"] for r in validation["evaluations"]] == [
        {"start_ms": START+600*HOUR, "end_ms": START+800*HOUR},
        {"start_ms": START+800*HOUR, "end_ms": START+1000*HOUR}]
    assert all(r["configuration"]["entry_notional"] == proposal["configuration"]["entry_notional"] for r in validation["evaluations"])
    assert verify_account_experiment(root, source, config) == report
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(CChanException):
        run_account_experiment(source, config, output_dir=root, **options())
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_validation_failure_does_not_publish_even_a_search_file(tmp_path):
    source = dataset(*raw_fixture())
    opts = {**options(), "validation_windows": [(START+1000*HOUR-1, START+1000*HOUR)]}
    with pytest.raises(CChanException):
        run_account_experiment(source, configuration(), output_dir=tmp_path / "run", **opts)
    assert list(tmp_path.iterdir()) == []


def test_publication_receipt_or_account_mutation_is_not_a_passed_experiment(tmp_path):
    source = dataset(*raw_fixture())
    config = configuration()
    root = tmp_path / "run"
    run_account_experiment(source, config, output_dir=root, **options())
    validation = root / "validation.json"
    body = json.loads(validation.read_bytes())
    body["evaluations"][0]["account"]["snapshot"]["equity"] = "999999"
    from CustomBuySellPoint.Decision import canonical_bytes
    validation.write_bytes(canonical_bytes(body))
    with pytest.raises(CChanException):
        verify_account_experiment(root, source, config)


def test_software_checks_do_not_accept_a_liquidation_episode_as_a_deployment_proposal():
    from ModelStrategy.parameterEvaluate.account_experiment import _score
    from .test_crypto_account_contract import opening, close, mark, conf
    from ModelStrategy.parameterEvaluate.crypto_account import evaluate_crypto_account
    # 后来价格恢复并最终退出，也不能抹掉早已触发处置的真实盯市状态。
    account = evaluate_crypto_account([opening(quantity="10"), mark(1000, "0.001"), close(2000, quantity="10")],
        conf(taker_fee="0.001"), start_ms=0, end_ms=3000)
    assert account["snapshot"]["status"] == "ready"
    import math
    assert math.isnan(_score({"account": account}, {"min_closed_positions": 1, "objective": "total_return"}))


def test_mutating_data_even_after_rehashing_files_cannot_pass_replay(tmp_path):
    source = dataset(*raw_fixture())
    config = configuration()
    root = tmp_path / "run"
    run_account_experiment(source, config, output_dir=root, **options())
    rows, marks, funding = raw_fixture()
    row = rows[650]
    rows[650] = (row[0], row[1], row[2]*1.01, row[3], row[4], row[5])
    with pytest.raises(CChanException):
        verify_account_experiment(root, dataset(rows, marks, funding), config)


def test_publication_failure_cleans_only_the_new_run_directory(tmp_path, monkeypatch):
    from ModelStrategy.parameterEvaluate import account_experiment as experiment
    original = experiment.write_json_once
    def broken(path, payload):
        if path.name == "proposal.json":
            raise OSError("simulated disk failure")
        return original(path, payload)
    monkeypatch.setattr(experiment, "write_json_once", broken)
    source = dataset(*raw_fixture())
    with pytest.raises(OSError):
        run_account_experiment(source, configuration(), output_dir=tmp_path / "run", **options())
    assert list(tmp_path.iterdir()) == []


def test_rehashed_nonwinning_trial_is_still_checked_against_the_real_inputs(tmp_path):
    import hashlib
    from CustomBuySellPoint.Decision import canonical_bytes
    source, config = dataset(*raw_fixture()), configuration()
    root = tmp_path / "run"
    run_account_experiment(source, config, output_dir=root, **options())
    search_path = root / "search.jsonl"
    records = [json.loads(line) for line in search_path.read_bytes().splitlines()]
    best = max(range(len(records)), key=lambda i: records[i]["score"])
    records[1-best]["eval"]["account"]["snapshot"]["equity"] = "999999"
    search_path.write_bytes(b"".join(canonical_bytes(r)+b"\n" for r in records))
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["files_sha256"]["search.jsonl"] = hashlib.sha256(search_path.read_bytes()).hexdigest()
    receipt["experiment_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in receipt.items() if k != "experiment_id"})).hexdigest()
    receipt_path.write_bytes(canonical_bytes(receipt))
    with pytest.raises(CChanException):
        verify_account_experiment(root, source, config)


@pytest.mark.parametrize("algorithm", ["bayes", "pbt"])
def test_other_algorithms_reproduce_the_same_fixed_small_account_experiment(tmp_path, algorithm):
    source, config = dataset(*raw_fixture()), configuration()
    opts = {**options(), "algorithm": algorithm}
    left = run_account_experiment(source, config, output_dir=tmp_path / "left", **opts)
    right = run_account_experiment(source, config, output_dir=tmp_path / "right", **opts)
    assert left == right
    for name in ("search.jsonl", "validation.json", "proposal.json", "receipt.json"):
        assert (tmp_path/"left"/name).read_bytes() == (tmp_path/"right"/name).read_bytes()
