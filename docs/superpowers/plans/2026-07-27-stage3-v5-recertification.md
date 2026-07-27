# Stage 3: v5 Conservative Recertification Implementation Plan

> **Execution rule:** Complete tasks and gates strictly in order. A failed BTC or
> multi-symbol gate produces a tracked rejection report and ends Stage 3; it never
> unlocks the next data tier.

**Goal:** Re-certify the single preregistered candidate
`S1bz + S2py10 + conviction#14 + z-limit(S2 non-pyramid) + z-exit` under
`conservative-v2`, using only 2021–2025 until every IS gate passes.

**Architecture:** Add a strict v5 certification specification and a portable
candidate-trade schema. Trusted local pickle caches are migration inputs only;
the certifier consumes versioned JSON plus logical OHLC/funding manifests. S1bz
already contains strategy-level fills and is audited against the raw fill bar;
S2py10 remains a signal intent and is replayed through the Stage-2 z-limit engine.
Eligible exits are replayed through first-touch z-exit rather than receiving a
fee-only flag. The certifier evaluates one gate at a time and has no general OOS
switch.

**Preregistered gates:**

- Risk selection: highest frozen grid value whose full-period and A/B/C maximum
  drawdown are all at most 25%.
- BTC IS: selected full-period Calmar at least 2.0; every A/B/C split has positive
  CAGR; all coverage, execution, and reference checks pass.
- ETH/SOL/BNB robustness, only after BTC passes: same candidate and selected risk;
  each full period is profitable, each split CAGR is at least -1%, and each symbol's
  worst drawdown is at most 35%. The -1% floor preserves the previously accepted
  "flat" BNB tolerance without allowing a material negative segment.
- Shared multi-symbol portfolio, only after all three robustness gates pass: positive
  CAGR, maximum drawdown at most 25%, and Calmar at least 1.0 under a shared 3x gross
  leverage cap.
- OOS, only after every IS gate passes: one immutable 2026-01-01 through
  2026-07-27 half-open evaluation using the frozen risk and input/config hashes.
  Acceptance remains the original objective: CAGR greater than 50%, drawdown below
  25%, and Calmar at least 2.0. No OOS-driven retry or parameter change is allowed.

---

### Task 1: Freeze the v5 schema, candidate, gates, and OOS lock

**Files:**
- Create: `ModelStrategy/research/candidate.py`
- Create: `ModelStrategy/research/certification_spec.py`
- Create: `ModelStrategy/research/configs/freeze_v5_candidate_v1.json`
- Test: `tests/research/test_candidate.py`
- Test: `tests/research/test_certification_spec.py`

- [x] **Step 1: Write failing schema/spec tests**

Prove exact-key validation, finite prices/risk, explicit `strategy_fill` versus
`signal_intent`, symbol/stack identity, portable JSON manifests, strict gate keys,
fixed component order, fixed split/window boundaries, and rejection of path escape,
unknown execution semantics, or any IS input timestamp at/after 2026-01-01.

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_candidate.py tests/research/test_certification_spec.py -q`

- [x] **Step 3: Implement the minimal strict loaders**

The candidate spec owns BTC plus conditional ETH/SOL/BNB relative inputs, bars DB,
per-symbol funding files, stack execution policies, z-exit reasons/patience, the
Stage-2 portfolio/execution policy, conviction values, risk grid, and gates. It also
contains the preregistered OOS window and acceptance thresholds, but the IS command
must not open any OOS input.

- [x] **Step 4: Verify GREEN and commit**

Record that gate values and the OOS window were frozen before candidate metrics were
computed.

### Task 2: Convert trusted BTC IS caches into portable guarded inputs

**Files:**
- Create: `ModelStrategy/research/migrate_candidate.py`
- Modify: `ModelStrategy/research/cli.py`
- Test: `tests/research/test_migrate_candidate.py`
- Test: `tests/research/test_cli.py`

- [x] **Step 1: Write failing migration tests**

Use a controlled test pickle and prove atomic output, source SHA-256, row counts,
schema version, symbol/stack matching, exact half-open time filtering, and hard
failure for missing required fields. `signal_intent` inputs require an explicit
boolean `is_pyramid`; a stale cache may not silently default it. Tests also prove a
2026 row causes failure before output creation.

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_migrate_candidate.py tests/research/test_cli.py -q`

- [x] **Step 3: Implement the isolated migration command**

Pickle loading exists only in this explicitly named migration surface. The formal
certifier imports no pickle module. Export all price-bearing fields needed for
execution auditing and include the source file manifest in the JSON envelope.

- [x] **Step 4: Migrate BTC 2021–2025 only**

Convert exactly these trusted sources without opening any `cache_26`, `2026`, or
open-ended cache:

- `BTC_USDT__S1bz[4H-1H-15M]__2021-01-01__2025-12-31.pkl`
- `BTC_USDT__S2py10[1D-4H]__2021-01-01__2025-12-31.pkl`

Write generated JSON beneath the external research root and record its logical hash.

- [x] **Step 5: Verify and commit**

### Task 2A: Remediate the discovered historical UTC offset before certification

**Trigger:** The first S1bz fill audit proved that the already-migrated JSON retained
the historical pickle's eight-hour-early epochs. Those generated files are invalid
certification inputs and must be replaced before Task 3 resumes.

**Files:**
- Modify: `ModelStrategy/research/candidate.py`
- Modify: `ModelStrategy/research/migrate_candidate.py`
- Modify: `ModelStrategy/research/cli.py`
- Modify: `ModelStrategy/research/certification_spec.py`
- Modify: `ModelStrategy/research/configs/freeze_v5_candidate_v1.json`
- Test: `tests/research/test_candidate.py`
- Test: `tests/research/test_migrate_candidate.py`
- Test: `tests/research/test_cli.py`
- Test: `tests/research/test_certification_spec.py`

- [x] Write failing tests proving the declared whole-second source offset is applied
  before IS/OOS checks and that the envelope binds raw/corrected bounds to it.
- [x] Require the migration CLI to declare the source offset explicitly; freeze
  `source_timestamp_offset_seconds=0` in formal execution because normalized JSON
  is already UTC and must not be corrected twice.
- [x] Regenerate both BTC IS JSON files with `+28800`, audit their logical hashes and
  corrected bounds, and prove a real S1bz maker fill aligns with its UTC bar.
- [x] Commit the remediation and only then resume Task 3.

**Remediation receipt:** S1bz contains 330 rows, generated SHA-256
`a33497ded20dc7fa363486b56493d8519b2034df5aea6e4cb7e8640efb13d618`,
and corrected bounds `1610622000..1765299600`. S2py10 contains 95 rows,
generated SHA-256
`87fa5014b18cdb5da9f3ba9c87a1adbaa3a16151cfb75a5a9b304829c59426fd`,
and corrected bounds `1613635200..1762776000`. Both envelopes declare source
offset `28800` under candidate envelope schema v2; formal execution declares zero
because it consumes those corrected timestamps. The environment-backed first S1bz
maker-fill audit passed on its UTC
`K_60M` bar without opening any 2026 input.

### Task 3: Audit filled entries and replay z-exit conservatively

**Files:**
- Modify: `ModelStrategy/research/execution.py`
- Create: `ModelStrategy/research/candidate_execution.py`
- Test: `tests/research/test_candidate_execution.py`

- [x] **Step 1: Write failing execution counterexamples**

Cover maker fills outside OHLC, synthetic fill bars, missing real bars, taker chase,
same-bar adverse stops, long/short symmetry, first-touch z-exit, z-exit patience
chase, stop-loss taker exits, exit-window gaps, and exits that would cross the IS
boundary.

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_candidate_execution.py -q`

- [x] **Step 3: Implement entry audit and exit replay**

For S1bz, preserve the strategy's actual fill timestamp/price but require a raw real
bar and verify maker price touch. For S2py10, reuse `build_intent()` and
`replay_trade()`. Reconstruct the initial stop from the price-bearing record and
risk distance. Replay only `reverse_bsp`, `trend_flip`, and `time_stop` through
z-exit; all risk exits remain taker. A maker exit changes the actual close timestamp
to its first real touch, while an unfilled order chases at the patience bar close.

- [x] **Step 4: Verify GREEN and commit**

**Execution receipt after UTC remediation:** all 330 S1bz strategy fills audited
against real `K_60M` bars (271 maker, 59 taker), with 180 maker and 150 taker
final exits after z-exit replay. All 95 S2py10 intents filled on `K_4H` (64 maker,
31 taker), with 70 maker and 25 taker final exits. The full environment-backed
audit reported zero errors and no replay crossed the 2026 boundary.

### Task 4: Build the auditable BTC IS gate and stop on failure

**Files:**
- Create: `ModelStrategy/research/certification.py`
- Modify: `ModelStrategy/research/cli.py`
- Create after real verification: `ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json`
- Test: `tests/research/test_certification.py`
- Test: `tests/research/test_cli.py`

- [x] **Step 1: Write failing gate/report/atomic CLI tests**

Prove ordered gate evaluation, risk selection, exact failure reasons, compact
reference comparison, input/spec hashes, no later-symbol reads after BTC failure,
and no OOS-capable argument on the IS command.

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_certification.py tests/research/test_cli.py -q`

- [x] **Step 3: Implement BTC assembly and report**

Load only BTC normalized trades, BTC logical bars, and BTC funding. Apply conviction
on actual fills, evaluate the frozen grid through the Stage-2 marked portfolio, and
emit metrics, execution counts, synthetic-gap disclosure, deltas to freeze-v4
conservative, every gate rule/observed value, and provenance.

- [x] **Step 4: Run the real BTC IS gate**

If BTC fails, freeze a `rejected` reference/report, explicitly confirm no ETH/SOL/BNB
or OOS input was opened, document the result, and mark Stage 3 complete. Do not run
Tasks 5–7. If it passes, freeze the BTC receipt and proceed to Task 5.

- [x] **Step 5: Verify and commit**

**BTC rejection receipt:** the first formal run used clean commit
`9fce518483b3ab10191161803a8aae54d12b6bf3`, spec hash
`ddf429b93fa67110bb8c80b544d746cb7c1c07215807c62a4311bd03a9dd2dfb`,
and selected only `risk_pct=0.005` under the 25% drawdown rule. BTC produced CAGR
`0.3195696056666606`, full/worst drawdown `0.19806622309040048`, and Calmar
`1.6134482734131004`; therefore `btc_full_calmar >= 2.0` failed and status is
`rejected`. A/B/C CAGRs remained positive. The receipt records 425/425 filled
intents, 335 maker/90 taker entries, 250 maker/175 taker exits, 9 same-bar stops,
and one portfolio skip. Funding stopped at the first raw 2026 BTC row without
parsing it. ETH/SOL/BNB, shared multi-symbol, and OOS remained unopened.

### Task 5: Run ETH/SOL/BNB robustness only if BTC passed

**Conditional:** Skip permanently when Task 4 rejects BTC.

- [x] Correctly skipped without resolving any ETH/SOL/BNB input because the BTC
  receipt is `rejected` at `btc_full_calmar`.

### Task 6: Run the shared multi-symbol portfolio only if Task 5 passed

**Conditional:** Skip permanently when any symbol gate fails.

- [x] Correctly skipped because the prerequisite symbol gates were never unlocked.

### Task 7: Unlock one OOS shot only if every IS receipt passed

**Conditional:** Skip permanently unless Tasks 4–6 all passed.

- [x] Correctly skipped; no OOS command was added or run because there is no passing
  BTC IS receipt.

## Stage-3 completion evidence

1. Candidate components and gates were tracked before real candidate metrics.
2. The certifier consumes only portable JSON and logical market/funding manifests.
3. Every attempted gate records its rule, observation, hashes, and stop reason.
4. No later-tier input is read after an earlier gate fails.
5. An OOS result exists only when all IS receipts passed; otherwise the report proves
   OOS remained sealed.
