# Stage 4: Fail-Closed Trading Safety and Dry-Run Recovery Plan

**Goal:** Make the trading boundary fail closed, persist actual order fills, recover
in-flight work idempotently, and exercise the whole lifecycle in dry-run without
creating a network exchange session or sending any real order.

**Current strategy constraint:** Stage 3 froze `freeze_v5_candidate_v1` as
`rejected`. Therefore this stage does not deploy v5. `testnet` and `live` modes must
require a separate passing/candidate strategy receipt; the tracked rejected receipt
must fail that check. Dry-run may exercise the generic plumbing while recording that
no certified strategy is active.

**Architecture:** Replace API-key-implies-live behavior with an explicit
`dry_run | testnet | live` safety policy. Persist an intent before submitting an
order, use deterministic client order IDs, and update records only from monotonic
exchange-reported fills. Use explicit states:

`signal -> submitted -> partially_filled -> open -> closing -> closed`

with terminal `canceled` and `rejected`. Opening zero fill never becomes a position;
partial fills use only actual quantity/average price; closing is reduce-only; a
restart reconciles pending client/order IDs instead of submitting a duplicate.

---

### Task 1: Fail-closed execution mode and strategy receipt gate

**Files:**
- Create: `Trade/SafetyPolicy.py`
- Modify: `Trade/CCXTTradeEngine.py`
- Modify: `Config/config_demo.yaml`
- Test: `tests/test_trade_safety.py`

- [x] Write failing tests proving API keys alone remain dry-run, unknown modes fail,
  testnet/live require a passing strategy receipt, and the tracked v5 rejection is
  refused.
- [x] Require `CHANPY_ENABLE_TESTNET=YES` for testnet and the exact
  `CHANPY_LIVE_TRADING_UNLOCK=I_ACCEPT_REAL_ORDERS` token for live; recheck a
  `CHANPY_KILL_SWITCH` before every non-dry-run order.
- [x] Never instantiate CCXT in dry-run and never include secrets in errors/logs.
- [x] Verify and commit.

### Task 2: Explicit order intent and bounded dry-run semantics

**Files:**
- Modify: `Trade/TradeEngine.py`
- Modify: `Trade/CCXTTradeEngine.py`
- Modify: `Trade/FutuTradeEngine.py`
- Test: `tests/test_trade_safety.py`

- [x] Write failing tests for requested versus filled quantity, partial/open status,
  client IDs, post-only/reduce-only parameters, spot oversell rejection, and swap
  reduce-only no-flip behavior.
- [x] Extend `COrderResult` with requested quantity and client identity; normalize
  only `open/closed/canceled/rejected` exchange states.
- [x] Add deterministic dry-run fill plans and monotonic order advancement so partial
  fill/recovery tests do not use a network exchange.
- [x] For contracts, query positions separately from spot balances and pass explicit
  leverage/position-side parameters; market post-only is illegal.
- [x] Verify and commit.

### Task 3: Persist the order state machine and migrate SQLite safely

**Files:**
- Modify: `Trade/SqliteDB.py`
- Modify: `Trade/MysqlDB.py`
- Modify: `Trade/db_util.py`
- Test: `tests/test_trade_state_machine.py`
- Modify: `tests/test_m6_trade.py`

- [x] Write failing tests that zero fill stays `submitted`, partial fill stores only
  actual quantity/average, fills are monotonic/idempotent, illegal transitions fail,
  and old SQLite files gain the new columns without losing rows.
- [x] Add open/cover client IDs, requested/current/cumulative fills, raw order status,
  attempt counters, last update, position side, strategy version, and risk multiplier.
- [x] Use conditional updates for intent acquisition so the same signal cannot be
  submitted twice.
- [x] Preserve legacy `cover` rows as terminal-readable while new records use
  `closed`.
- [x] Verify and commit.

### Task 4: Idempotent submit, partial fill, cancel/retry, and restart recovery

**Files:**
- Modify: `Trade/TradeEngine.py`
- Modify: `Trade/Script/MakeOpenTrade.py`
- Modify: `Trade/Script/RealTimeTracker.py`
- Test: `tests/test_trade_state_machine.py`
- Test: `tests/test_m6_trade.py`

- [x] Persist open/close intent before exchange submission and derive deterministic
  client IDs from the database record/attempt.
- [x] Apply only exchange-reported cumulative fills; do not use `filled or planned`.
- [x] Recover opening and closing orders by order ID or client ID; repeated recovery
  must not resubmit or double-apply fills.
- [x] Cancel/retry a close only after cancellation is confirmed, then submit only the
  remaining quantity as reduce-only with a new client ID.
- [x] Verify and commit.

### Task 5: Offline dry-run acceptance and operator documentation

**Files:**
- Modify: `README_FULL.md`
- Modify: `STRATEGY_LOG.md`
- Modify: `CLAUDE.md`
- Modify: `Config/config_demo.yaml`
- Test: `tests/test_trade_state_machine.py`

- [ ] Run a temporary-SQLite lifecycle: signal -> zero/partial fill -> restart -> full
  open -> partial reduce-only close -> restart -> closed. Assert balances, positions,
  states, client IDs, and no duplicate submission.
- [ ] Prove the tracked rejected v5 receipt blocks testnet/live and that no test opens
  a network exchange or invokes a real `create_order` implementation.
- [ ] Document exact dry-run commands, safety environment variables, receipt rule,
  remaining exchange-specific testnet gaps, and the fact that real trading remains
  locked.
- [ ] Run focused tests, full offline regression, compileall, diff-check, and an
  independent read-only review before merging.

## Completion evidence

1. API keys never select a non-dry-run mode.
2. A rejected/missing strategy receipt prevents testnet/live construction.
3. Zero fill produces no open position; partial fills persist only actual exposure.
4. Restart reconciliation is idempotent for both open and close orders.
5. Dry-run spot cannot oversell and contract reduce-only cannot increase/flip risk.
6. No network exchange or real order path is exercised during Stage 4.
