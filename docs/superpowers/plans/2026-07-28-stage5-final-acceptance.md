# Stage 5: Final Acceptance and Pre-Live Handoff Plan

**Goal:** Produce an auditable final acceptance record whose strategy numbers,
execution status, offline tests, and operator checklist agree, while keeping testnet
and live trading locked.

**Current decision:** `freeze_v5_candidate_v1` is `rejected` at the BTC 2021-2025
IS gate (Calmar 1.613 < 2.0). Stage 5 does not open ETH/SOL/BNB candidate inputs,
shared portfolio certification, or any new 2026 OOS result. It cannot create a
`candidate` receipt.

---

### Task 1: Lock final report and documentation consistency

**Files:**
- Create: `tests/test_final_acceptance.py`
- Create: `docs/superpowers/reports/2026-07-28-final-acceptance.md`
- Modify: `README_FULL.md`
- Modify: `CLAUDE.md`
- Modify: `STRATEGY_LOG.md`

- [ ] Write failing tests that compare the documented v4/v5 metrics, cutoff,
  execution model, status, and trading lock against tracked JSON references.
- [ ] Record the five-stage decision trail without converting the rejected v5 into a
  deployable receipt or exposing secrets/machine-specific data roots.
- [ ] Add a pre-live checklist with explicit testnet evidence requirements and a
  separate irreversible live authorization gate.
- [ ] Verify and commit.

### Task 2: Re-run clean, read-only strategy references

**Commands:**
- `baseline` for freeze-v4 legacy reference
- `compare` for freeze-v4 conservative-v2 reference
- `certify-v5-btc-is` for the rejected v5 BTC IS reference

- [ ] Run from a clean Stage 5 commit with explicit external read-only roots.
- [ ] Confirm reference comparisons pass and no 2026 candidate/OOS artifact is
  generated or modified.
- [ ] Record commands, commit, environment, metric summaries, and reference hashes in
  the acceptance report.
- [ ] Verify and commit.

### Task 3: Final offline software acceptance

- [ ] Run focused research, safety, state-machine, legacy M6, and documentation
  consistency tests.
- [ ] Run the complete `pytest -m "not network"` suite.
- [ ] Run compileall and `git diff --check`; inspect tracked/untracked files and
  confirm no credentials or external research data entered the repository.
- [ ] Run a final independent read-only P0-P2 review and fix any confirmed issue.
- [ ] Verify and commit.

### Task 4: Merge and release decision

- [ ] Merge the clean Stage 5 branch into `full-version` with an auditable decision
  commit.
- [ ] Re-run the final focused acceptance checks on the merged commit.
- [ ] Record the release decision as **research/dry-run accepted; testnet/live not
  approved** and list the exact external evidence still required.
- [ ] Mark the five-stage goal complete only after all preceding evidence is present.

## Completion evidence

1. Tracked reports and docs agree on the 2021-2025 half-open cutoff,
   `conservative-v2`, risk 0.005, CAGR 31.957%, drawdown 19.807%, Calmar 1.613,
   and `rejected` status.
2. No new 2026 OOS result or candidate receipt exists.
3. Offline full regression and focused integration tests pass on the final code.
4. Dry-run restart acceptance cannot create an exchange session or real order.
5. The checklist cannot be interpreted as testnet/live approval; both remain locked.
