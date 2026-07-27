# Stage 2 Remediation: UTC-align Historical Research Inputs

**Trigger:** The first Stage-3 actual-fill audit proved that a cached S1bz record
whose displayed `CTime` was `2021-01-14 11:00` carried epoch `1610593200`
(`03:00 UTC`). The maker price was impossible on the 03:00 bar and valid on the
11:00 bar. `CTime.set_timestamp()` used a naive datetime, so Asia/Shanghai hosts
shifted crypto epochs eight hours earlier than their UTC OHLC fields.

**Goal:** Repair the invalid Stage-2 time alignment, re-freeze freeze-v4 under
`conservative-v2`, and prevent future crypto caches from depending on host timezone.
Do not alter the historical `legacy-v1` reference and do not read 2026 strategy data.

**Architecture:** Preserve legacy cache bytes and legacy reproduction. Add explicit
UTC semantics to crypto data readers for newly generated records. Give the
conservative specification an audited `source_timestamp_offset_seconds`; normalize
legacy cache timestamps before any market/funding lookup, conviction event, split
assignment, or manifest boundary check. Test fixtures may preregister offset zero,
while the tracked freeze-v4 conservative spec declares `28800` for the historical
Asia/Shanghai-generated caches.

---

### Task 1: Make crypto `CTime` epochs host-timezone independent

**Files:**
- Modify: `Common/CTime.py`
- Modify: `DataAPI/OfflineDataAPI.py`
- Modify: `DataAPI/ccxt.py`
- Create: `tests/test_ctime_timezone.py`

- [x] Write failing tests proving an explicit UTC `CTime` equals the same epoch
  regardless of process timezone, while the default constructor preserves legacy
  local semantics for non-crypto adapters.
- [x] Prove offline SQLite/CSV and CCXT readers attach UTC semantics to crypto bars.
- [x] Implement an optional timezone on `CTime` and pass `timezone.utc` only from
  crypto readers.
- [x] Run focused data/multilevel tests and commit.

### Task 2: Version and validate the historical timestamp correction

**Files:**
- Modify: `ModelStrategy/research/spec.py`
- Modify: `ModelStrategy/research/configs/freeze_v4_conservative_v2.json`
- Modify: `tests/research/test_spec.py`

- [ ] Add a failing strict-spec test for the exact
  `source_timestamp_offset_seconds` execution key.
- [ ] Accept only a whole-second integer in a bounded range; legacy-v1 continues to
  have no execution block.
- [ ] Track `28800` for freeze-v4 conservative; fixture specs explicitly use zero.
- [ ] Verify spec hash drift is intentional and commit.

### Task 3: Normalize before every conservative timeline decision

**Files:**
- Modify: `ModelStrategy/research/conservative_baseline.py`
- Modify: `tests/research/test_conservative_baseline.py`
- Modify: `tests/research/test_execution.py`

- [ ] Write a failing assembly test where a raw cache timestamp is eight hours early
  and only the corrected bar can supply the signal price/fill.
- [ ] Add failing boundary tests proving correction happens before IS checks and a
  corrected timestamp at/after 2026 is rejected.
- [ ] Copy source trades with corrected open/close timestamps before window checks,
  execution replay, conviction, split membership, and funding/mark evaluation.
- [ ] Report both raw and corrected timestamp bounds plus the declared offset in each
  trade manifest.
- [ ] Re-run real execution replay and prove its logical market/funding inputs remain
  half-open 2021–2025.

### Task 4: Recompute and re-freeze Stage 2

**Files:**
- Modify: `ModelStrategy/research/baselines/freeze_v4_conservative_v2.json`
- Modify: `README_FULL.md`
- Modify: `STRATEGY_LOG.md`
- Modify: `docs/superpowers/plans/2026-07-27-stage2-conservative-backtest.md`

- [ ] Run the real comparison without a reference and inspect execution counts,
  first/last timestamps, gaps, fees, funding, risk selection, and split metrics.
- [ ] Update the compact reference only from the corrected report, then rerun with
  `--conservative-reference`.
- [ ] Prove the legacy CLI remains byte/metric compatible.
- [ ] Run research tests with real roots, full offline tests, compileall, diff-check,
  and a read-only review.
- [ ] Merge only after all gates pass; then resume Stage 3 from its preregistered plan.

## Completion evidence

1. A synthetic timezone counterexample fails before the fix and passes after it.
2. The tracked conservative report explicitly states the +28800-second source
   correction and uses corrected timestamps for market/funding alignment.
3. The historical legacy reference remains exact.
4. No `cache_26`, 2026 candidate report, or live-order path is opened.
