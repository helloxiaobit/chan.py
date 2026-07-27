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

- [ ] **Step 1: Write failing migration tests**

Use a controlled test pickle and prove atomic output, source SHA-256, row counts,
schema version, symbol/stack matching, exact half-open time filtering, and hard
failure for missing required fields. `signal_intent` inputs require an explicit
boolean `is_pyramid`; a stale cache may not silently default it. Tests also prove a
2026 row causes failure before output creation.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/research/test_migrate_candidate.py tests/research/test_cli.py -q`

- [ ] **Step 3: Implement the isolated migration command**

Pickle loading exists only in this explicitly named migration surface. The formal
certifier imports no pickle module. Export all price-bearing fields needed for
execution auditing and include the source file manifest in the JSON envelope.

- [ ] **Step 4: Migrate BTC 2021–2025 only**

Convert exactly these trusted sources without opening any `cache_26`, `2026`, or
open-ended cache:

- `BTC_USDT__S1bz[4H-1H-15M]__2021-01-01__2025-12-31.pkl`
- `BTC_USDT__S2py10[1D-4H]__2021-01-01__2025-12-31.pkl`

Write generated JSON beneath the external research root and record its logical hash.

- [ ] **Step 5: Verify and commit**

### Task 3: Audit filled entries and replay z-exit conservatively

**Files:**
- Modify: `ModelStrategy/research/execution.py`
- Create: `ModelStrategy/research/candidate_execution.py`
- Test: `tests/research/test_candidate_execution.py`

- [ ] **Step 1: Write failing execution counterexamples**

Cover maker fills outside OHLC, synthetic fill bars, missing real bars, taker chase,
same-bar adverse stops, long/short symmetry, first-touch z-exit, z-exit patience
chase, stop-loss taker exits, exit-window gaps, and exits that would cross the IS
boundary.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/research/test_candidate_execution.py -q`

- [ ] **Step 3: Implement entry audit and exit replay**

For S1bz, preserve the strategy's actual fill timestamp/price but require a raw real
bar and verify maker price touch. For S2py10, reuse `build_intent()` and
`replay_trade()`. Reconstruct the initial stop from the price-bearing record and
risk distance. Replay only `reverse_bsp`, `trend_flip`, and `time_stop` through
z-exit; all risk exits remain taker. A maker exit changes the actual close timestamp
to its first real touch, while an unfilled order chases at the patience bar close.

- [ ] **Step 4: Verify GREEN and commit**

### Task 4: Build the auditable BTC IS gate and stop on failure

**Files:**
- Create: `ModelStrategy/research/certification.py`
- Modify: `ModelStrategy/research/cli.py`
- Create after real verification: `ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json`
- Test: `tests/research/test_certification.py`
- Test: `tests/research/test_cli.py`

- [ ] **Step 1: Write failing gate/report/atomic CLI tests**

Prove ordered gate evaluation, risk selection, exact failure reasons, compact
reference comparison, input/spec hashes, no later-symbol reads after BTC failure,
and no OOS-capable argument on the IS command.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/research/test_certification.py tests/research/test_cli.py -q`

- [ ] **Step 3: Implement BTC assembly and report**

Load only BTC normalized trades, BTC logical bars, and BTC funding. Apply conviction
on actual fills, evaluate the frozen grid through the Stage-2 marked portfolio, and
emit metrics, execution counts, synthetic-gap disclosure, deltas to freeze-v4
conservative, every gate rule/observed value, and provenance.

- [ ] **Step 4: Run the real BTC IS gate**

If BTC fails, freeze a `rejected` reference/report, explicitly confirm no ETH/SOL/BNB
or OOS input was opened, document the result, and mark Stage 3 complete. Do not run
Tasks 5–7. If it passes, freeze the BTC receipt and proceed to Task 5.

- [ ] **Step 5: Verify and commit**

### Task 5: Run ETH/SOL/BNB robustness only if BTC passed

**Conditional:** Skip permanently when Task 4 rejects BTC.

- [ ] Regenerate any stale S2py10 cache whose records lack explicit pyramid identity;
  never default the field.
- [ ] Migrate each symbol's 2021–2025 inputs and run gates strictly ETH, then SOL,
  then BNB, stopping and freezing `rejected` at the first failure.
- [ ] Add synthetic tests for symbol isolation, funding mapping, and stop-on-failure.
- [ ] Commit the gate receipts and compact reference.

### Task 6: Run the shared multi-symbol portfolio only if Task 5 passed

**Conditional:** Skip permanently when any symbol gate fails.

- [ ] Add a shared marked-portfolio assembly with per-symbol marks/funding and a
  shared 3x gross leverage limit.
- [ ] Prove timestamp ordering, per-symbol funding, and symbol-specific gaps in tests.
- [ ] Freeze the multi-symbol gate receipt or formal rejection.

### Task 7: Unlock one OOS shot only if every IS receipt passed

**Conditional:** Skip permanently unless Tasks 4–6 all passed.

- [ ] Add a separate one-shot command that requires the exact passing IS receipt hash,
  clean candidate spec hash, frozen risk, and preregistered OOS window.
- [ ] Prove wrong/missing receipts, retries, wider windows, and dirty inputs fail before
  OOS data is opened.
- [ ] Run exactly once, freeze `candidate`, `rejected`, or `insufficient-data`, and never
  tune from its output.

## Stage-3 completion evidence

1. Candidate components and gates were tracked before real candidate metrics.
2. The certifier consumes only portable JSON and logical market/funding manifests.
3. Every attempted gate records its rule, observation, hashes, and stop reason.
4. No later-tier input is read after an earlier gate fails.
5. An OOS result exists only when all IS receipts passed; otherwise the report proves
   OOS remained sealed.
