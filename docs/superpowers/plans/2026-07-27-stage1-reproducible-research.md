# Stage 1 Reproducible Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repository-owned, deterministic and OOS-guarded command that reproduces the corrected freeze-v4 2021–2025 baseline from explicit external inputs.

**Architecture:** A small `ModelStrategy.research` package owns versioned specifications, validated trade records, logical input manifests, the legacy baseline assembly, and a CLI. Large data remains under an explicit external research root; only code, the strategy specification, and a compact reference result are tracked. The baseline path reads only timestamps before 2026-01-01 and produces provenance-rich JSON in the already-ignored `backtest_output/` directory.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `sqlite3`, `subprocess`), existing `conviction.py` and `portfolio_eval.py`, pytest.

---

## File map

- Create `ModelStrategy/research/__init__.py`: public research package surface and schema constants.
- Create `ModelStrategy/research/boundary.py`: UTC parsing and IS/OOS boundary enforcement.
- Create `ModelStrategy/research/schema.py`: validated, mutable trade record used by existing portfolio code.
- Create `ModelStrategy/research/provenance.py`: canonical JSON, hashes, Git/runtime provenance, and logical SQLite manifests.
- Create `ModelStrategy/research/spec.py`: versioned JSON strategy-spec loader and path validation.
- Create `ModelStrategy/research/baseline.py`: freeze-v4 legacy assembly, z-limit replay, risk selection, report generation, and reference comparison.
- Create `ModelStrategy/research/cli.py`: `baseline` command with explicit paths and atomic output.
- Create `ModelStrategy/research/configs/freeze_v4_legacy_v1.json`: frozen 2021–2025 specification.
- Create `ModelStrategy/research/baselines/freeze_v4_legacy_v1.json`: compact authoritative IS reference metrics.
- Create `tests/research/__init__.py`: research-test package marker.
- Create `tests/research/test_boundary.py`: OOS guard tests.
- Create `tests/research/test_schema.py`: trade schema tests.
- Create `tests/research/test_provenance.py`: deterministic serialization and logical-manifest tests.
- Create `tests/research/test_spec.py`: specification and relative-path validation tests.
- Create `tests/research/test_baseline.py`: z-limit, risk calibration, reference comparison, and end-to-end fixture tests.
- Create `tests/research/test_cli.py`: command success/failure and atomic-output tests.
- Modify `README_FULL.md`: document the tracked research entry point and data-root contract.
- Modify `STRATEGY_LOG.md`: record stage-1 engineering completion without changing strategy conclusions.

### Task 1: Enforce the 2026 research boundary

**Files:**
- Create: `ModelStrategy/research/__init__.py`
- Create: `ModelStrategy/research/boundary.py`
- Create: `tests/research/__init__.py`
- Test: `tests/research/test_boundary.py`

- [ ] **Step 1: Write the failing boundary tests**

```python
from datetime import datetime, timezone

import pytest

from ModelStrategy.research.boundary import (
    IS_END_EXCLUSIVE,
    ResearchBoundaryError,
    parse_utc,
    require_is_timestamp,
    require_is_window,
)


def test_parse_utc_is_timezone_independent():
    assert parse_utc("2026-01-01") == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


def test_is_timestamp_rejects_2026_boundary():
    with pytest.raises(ResearchBoundaryError, match="OOS"):
        require_is_timestamp(IS_END_EXCLUSIVE)


def test_is_window_accepts_2021_through_2025_only():
    begin, end = require_is_window("2021-01-01", "2026-01-01")
    assert begin < end == IS_END_EXCLUSIVE


def test_is_window_rejects_end_after_2026_boundary():
    with pytest.raises(ResearchBoundaryError, match="2026-01-01"):
        require_is_window("2021-01-01", "2026-01-02")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/research/test_boundary.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'ModelStrategy.research'`.

- [ ] **Step 3: Implement the minimal UTC boundary API**

```python
# ModelStrategy/research/boundary.py
from datetime import datetime, timezone

IS_END_EXCLUSIVE = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


class ResearchBoundaryError(ValueError):
    pass


def parse_utc(value: str) -> float:
    text = value if "T" in value else f"{value}T00:00:00"
    return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
        tzinfo=timezone.utc
    ).timestamp()


def require_is_timestamp(ts: float) -> float:
    if ts >= IS_END_EXCLUSIVE:
        raise ResearchBoundaryError("OOS timestamp is not allowed before the IS gate passes")
    return ts


def require_is_window(begin: str, end_exclusive: str) -> tuple[float, float]:
    begin_ts, end_ts = parse_utc(begin), parse_utc(end_exclusive)
    if begin_ts >= end_ts:
        raise ResearchBoundaryError("research window must be increasing")
    if end_ts > IS_END_EXCLUSIVE:
        raise ResearchBoundaryError("IS window cannot extend beyond 2026-01-01")
    return begin_ts, end_ts
```

`ModelStrategy/research/__init__.py` must export `IS_END_EXCLUSIVE` and `ResearchBoundaryError`. `tests/research/__init__.py` is empty.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `pytest tests/research/test_boundary.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit the boundary**

Stage the four files and commit with a Lore message whose intent is to prevent accidental OOS access. Record the exact pytest command in `Tested:`.

### Task 2: Validate and normalize cached trade records

**Files:**
- Create: `ModelStrategy/research/schema.py`
- Test: `tests/research/test_schema.py`

- [ ] **Step 1: Write the failing schema tests**

```python
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
    path.write_text(__import__("json").dumps([{**VALID, "open_ts": 1767225600.0,
                                               "close_ts": 1767229200.0}]))
    with pytest.raises(ResearchBoundaryError):
        load_trades(path, is_only=True)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/research/test_schema.py -q`

Expected: import fails because `schema.py` does not exist.

- [ ] **Step 3: Implement the minimal trade schema**

Implement a mutable `@dataclass ResearchTrade` with `open_ts`, `close_ts`, `profit_rate`, `risk_rate`, `bs_type`, `is_buy`, `is_pyramid=False`, plus optional `reason`, `close_price`, `stack`, `exit_maker=False`, and `risk_mult=1.0`. `from_mapping()` must coerce numeric fields to finite floats, require `risk_rate > 0`, require `close_ts >= open_ts`, require a non-empty `bs_type`, and require an actual boolean for `is_buy`. `to_mapping()` must emit fields in a fixed order. `load_trades(path, is_only=True)` must require a JSON list, convert every item, and apply `require_is_timestamp()` to both timestamps when `is_only` is true.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `pytest tests/research/test_schema.py tests/research/test_boundary.py -q`

Expected: `8 passed`.

- [ ] **Step 5: Commit the schema**

Commit the implementation and tests with `Tested: pytest tests/research/test_schema.py tests/research/test_boundary.py -q`.

### Task 3: Produce deterministic specifications and provenance

**Files:**
- Create: `ModelStrategy/research/spec.py`
- Create: `ModelStrategy/research/provenance.py`
- Create: `ModelStrategy/research/configs/freeze_v4_legacy_v1.json`
- Test: `tests/research/test_spec.py`
- Test: `tests/research/test_provenance.py`

- [ ] **Step 1: Write failing specification and provenance tests**

Tests must demonstrate these concrete behaviors:

```python
def test_canonical_json_is_key_order_independent():
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})


def test_spec_rejects_absolute_input_path(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(minimal_spec(s1_path="C:/private/cache.json")))
    with pytest.raises(ValueError, match="relative"):
        load_spec(path)


def test_spec_rejects_oos_window(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(minimal_spec(end_exclusive="2026-01-02")))
    with pytest.raises(ResearchBoundaryError):
        load_spec(path)


def test_sqlite_manifest_hashes_only_selected_rows(tmp_path):
    db = build_fixture_db(tmp_path, rows=[
        (1609459200000, "BTC/USDT", "K_60M", 1, 2, 0.5, 1.5),
        (1767225600000, "BTC/USDT", "K_60M", 9, 9, 9, 9),
    ])
    first = sqlite_kline_manifest(db, "BTC/USDT", "K_60M", 1609459200000, 1640995200000)
    mutate_only_oos_row(db)
    second = sqlite_kline_manifest(db, "BTC/USDT", "K_60M", 1609459200000, 1640995200000)
    assert first == second
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/research/test_spec.py tests/research/test_provenance.py -q`

Expected: imports fail because `spec.py` and `provenance.py` do not exist.

- [ ] **Step 3: Implement canonical JSON, hashes, and the versioned spec**

`canonical_json_bytes(value)` must use UTF-8, `ensure_ascii=False`, `sort_keys=True`, compact separators, `allow_nan=False`, and a trailing newline. `sha256_bytes()` and `sha256_file()` return lowercase hex. `sqlite_kline_manifest()` must query only the requested symbol/level/timestamp half-open interval, hash canonical row arrays in query order, and return row count plus first/last timestamp and logical SHA-256. `git_provenance()` returns `commit` and `dirty` without raising when Git is unavailable.

`ResearchSpec` must expose `strategy_id`, `execution_model`, window timestamps, input paths, risk grid, portfolio values, conviction values, z-limit settings, and split windows. `load_spec()` validates schema version `1`, execution model `legacy-v1`, IS boundary, non-empty increasing risk grid, and relative input paths.

The tracked JSON specification must encode exactly:

```json
{
  "schema_version": 1,
  "strategy_id": "freeze_v4",
  "execution_model": "legacy-v1",
  "window": {"begin": "2021-01-01", "end_exclusive": "2026-01-01"},
  "inputs": {
    "s1_trades": "from_session_b/cache_2125_S1.json",
    "s2_trades": "cache_2125_S2py10_ispyr.json",
    "bars_db": "btc_mlv.db"
  },
  "risk_grid": [0.005, 0.0075, 0.01, 0.0125, 0.015],
  "portfolio": {"taker_fee": 0.0005, "maker_fee": 0.0002, "max_concurrent": 4,
                "max_leverage": 3.0, "max_pos_leverage": 1.5, "target_max_drawdown": 0.25},
  "conviction": {"co_dir_mult": 1.5, "opp_dir_mult": 1.0,
                 "bs_mults": {"1": 0.8, "1p": 1.2}, "mult_cap": 2.0},
  "zlimit": {"patience": 8, "s1_level": "K_60M", "s1_ms": 3600000,
             "s2_level": "K_4H", "s2_ms": 14400000},
  "splits": {
    "A(21-23)": ["2021-01-01", "2024-01-01"],
    "B(2024)": ["2024-01-01", "2025-01-01"],
    "C(2025)": ["2025-01-01", "2026-01-01"]
  }
}
```

- [ ] **Step 4: Run focused and existing configuration tests**

Run: `pytest tests/research/test_spec.py tests/research/test_provenance.py tests/test_env_config.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the specification boundary**

Commit the five files with trailers recording the logical-hash and OOS-range constraints.

### Task 4: Reproduce the corrected freeze-v4 IS baseline

**Files:**
- Create: `ModelStrategy/research/baseline.py`
- Create: `ModelStrategy/research/baselines/freeze_v4_legacy_v1.json`
- Test: `tests/research/test_baseline.py`

- [ ] **Step 1: Write failing z-limit and calibration tests**

Build a tiny SQLite fixture with `kline(ts, symbol, lv, o, h, l, c)` and JSON trade fixtures. Assert:

```python
def test_pyramid_trade_is_never_reclassified_as_maker():
    normal, pyramid = make_trade(is_pyramid=False), make_trade(is_pyramid=True)
    bars = BarsFixture(close_at_open=100, next_low=99, next_high=101)
    apply_zlimit([normal, pyramid], bars, patience=8)
    assert normal.bs_type == "z1"
    assert pyramid.bs_type == "1"


def test_unreached_limit_remains_taker():
    trade = make_trade(is_buy=True)
    bars = BarsFixture(close_at_open=100, future_lows=[101] * 8)
    apply_zlimit([trade], bars, patience=8)
    assert trade.bs_type == "1"


def test_run_baseline_selects_highest_risk_within_drawdown(tmp_path):
    report = run_baseline(fixture_spec(tmp_path), research_root=tmp_path,
                          provenance={"commit": "test", "dirty": False})
    feasible = [row for row in report["risk_calibration"] if row["passed"]]
    assert report["result"]["risk_pct"] == max(row["risk_pct"] for row in feasible)
```

Add a reference-comparison test with the tracked metric file. It may skip only when `CHANPY_RESEARCH_ROOT` is absent; when set, it must run the real inputs and compare risk, full CAGR/DD and all A/B/C values with absolute tolerance `1e-12` for unrounded fields and exact equality for rounded fields.

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/research/test_baseline.py -q`

Expected: import fails because `baseline.py` does not exist.

- [ ] **Step 3: Implement the legacy baseline runner**

Implement these focused functions:

- `load_bars(db_path, symbol, level, level_ms, begin_ts, end_ts)`: query only IS rows; expose end timestamps, low/high pairs, and close-by-end-time.
- `apply_zlimit(trades, bars, patience)`: reproduce the corrected historical rule exactly, including skipping `is_pyramid` and already-prefixed trades.
- `assemble_trades(spec, research_root)`: load S1/S2 JSON, apply the correct level, merge, sort, and call existing `stamp_conviction()`.
- `calibrate_risk(trades, spec)`: construct `CPortfolioConfig` from the spec for every grid value, calculate full and split metrics, and select the highest risk whose worst drawdown is at most the target.
- `run_baseline(spec, research_root, provenance=None)`: return schema version, strategy/execution IDs, spec hash, logical input manifests, provenance, calibration table, and selected result. It must fail if any loaded trade or queried bar reaches the OOS boundary.
- `compare_reference(report, reference)`: return a structured list of metric mismatches and never silently round before comparing.

Track this IS-only reference:

```json
{
  "schema_version": 1,
  "strategy_id": "freeze_v4",
  "execution_model": "legacy-v1",
  "risk_pct": 0.0075,
  "is_2125": {
    "cagr": 0.46917167124699044,
    "full_dd": 0.24312663043838884,
    "worst_dd": 0.24312663043838884,
    "splits": {
      "A(21-23)": {"cagr": 0.489, "dd": 0.243, "calmar": 2.01},
      "B(2024)": {"cagr": 0.601, "dd": 0.112, "calmar": 5.37},
      "C(2025)": {"cagr": 0.289, "dd": 0.11, "calmar": 2.62}
    }
  }
}
```

- [ ] **Step 4: Run unit and real-data verification**

Run: `pytest tests/research/test_baseline.py -q`

Expected: fixture tests pass and the real-data test skips without the environment variable.

Run: `$env:CHANPY_RESEARCH_ROOT='C:\chanpy\research'; pytest tests/research/test_baseline.py -q`

Expected: all tests pass with no skip and the reference comparison has zero mismatches.

- [ ] **Step 5: Commit the baseline implementation**

Commit implementation, tests, and reference metrics. Record both pytest commands and explicitly state that no 2026 trade stream was loaded.

### Task 5: Add the atomic CLI and stage-1 documentation

**Files:**
- Create: `ModelStrategy/research/cli.py`
- Test: `tests/research/test_cli.py`
- Modify: `README_FULL.md`
- Modify: `STRATEGY_LOG.md`

- [ ] **Step 1: Write failing CLI tests**

Use `subprocess.run([sys.executable, "-m", "ModelStrategy.research.cli", ...])` against fixture inputs. Assert a successful command writes valid JSON, a reference mismatch exits non-zero, an output path is not left behind after failure, and a fixture spec whose `end_exclusive` is `2026-01-02` is rejected before data loading.

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/research/test_cli.py -q`

Expected: subprocess fails because `ModelStrategy.research.cli` does not exist.

- [ ] **Step 3: Implement the CLI with atomic output**

The supported command is:

```text
python -m ModelStrategy.research.cli baseline \
  --spec ModelStrategy/research/configs/freeze_v4_legacy_v1.json \
  --research-root C:\chanpy\research \
  --reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json \
  --output backtest_output/research/freeze_v4_legacy_v1.json
```

`--research-root`, `--spec`, `--reference`, and `--output` are mandatory. The CLI validates all inputs before creating output, writes to a sibling temporary file, calls `os.replace()` only after successful reference comparison, prints a one-line Chinese summary, and returns non-zero for boundary, schema, missing-file, or metric mismatch errors. It has no OOS or `--shot` option.

- [ ] **Step 4: Update documentation and run the real command**

`README_FULL.md` must explain the external-data contract, the exact command, generated provenance, and the fact that stage 1 is IS-only. `STRATEGY_LOG.md` must add an engineering entry that preserves the strategy conclusion and correct the stale `bs1p` value from `1.25` to `1.2` plus corrected v4 metrics.

Run the exact command above. Expected: exit 0, a report under `backtest_output/research/`, selected risk `0.0075`, and zero reference mismatches.

- [ ] **Step 5: Run stage-1 gate and commit**

Run:

```text
pytest tests/research -q
pytest -q -m "not network"
python -m compileall -q ModelStrategy/research tests/research
git diff --check
```

Expected: research tests pass; the existing offline suite stays green; compileall and diff check return 0. Commit the CLI, tests, and docs with full Lore verification trailers.

## Stage-1 completion evidence

Stage 1 is complete only when all checkboxes above are satisfied and the following evidence exists together:

1. The real-data CLI exits 0 using `C:\chanpy\research` and produces an IS-only report.
2. The report declares `legacy-v1`, selected risk `0.0075`, and exact corrected freeze-v4 IS metrics.
3. Its manifests cover only 2021–2025 logical rows even though the external database contains newer rows.
4. `pytest -q -m "not network"` passes after the new tests are included.
5. No generated output, data file, database, pickle, secret, or 2026 candidate result is staged in Git.
