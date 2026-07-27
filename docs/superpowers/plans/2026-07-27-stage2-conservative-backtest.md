# Stage 2 Conservative Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately versioned `conservative-v2` execution model that replays fills, marks open positions to market, charges funding and fees, and produces an auditable freeze-v4 difference report without altering `legacy-v1`.

**Architecture:** Keep `portfolio_eval()` and the tracked freeze-v4 legacy reference byte-for-byte compatible. Convert the existing IS trade intents plus SQLite OHLC into explicit execution trades, then feed those trades, hourly mark bars, and funding events to a new event-driven conservative portfolio evaluator. A new CLI command compares `legacy-v1` with `conservative-v2`; both paths remain limited to 2021–2025.

**Tech Stack:** Python 3 standard library, existing `ResearchSpec`/`ResearchTrade`, existing SQLite and funding CSV assets, pytest.

---

## File map

- Modify `ModelStrategy/research/spec.py`: accept `conservative-v2`, its market-data input, and explicit execution policy.
- Create `ModelStrategy/research/configs/freeze_v4_conservative_v2.json`: preregistered conservative policy.
- Create `ModelStrategy/research/market.py`: OHLC/funding value objects, IS-only loaders, gap checks, and logical manifests.
- Create `ModelStrategy/research/execution.py`: replay z-limit fills, taker fallback, same-bar adverse stop, and execution-trade construction.
- Create `ModelStrategy/research/conservative.py`: mark-to-market portfolio evaluator.
- Create `ModelStrategy/research/conservative_baseline.py`: risk calibration and legacy/conservative difference report.
- Modify `ModelStrategy/research/cli.py`: add `compare` command with explicit research/data roots.
- Create `ModelStrategy/research/baselines/freeze_v4_conservative_v2.json`: tracked IS result after real-data verification.
- Create `tests/research/test_market.py`: OHLC/funding boundary and gap tests.
- Create `tests/research/test_execution.py`: fill and same-bar ordering tests.
- Create `tests/research/test_conservative.py`: MTM, fees, funding, leverage, long/short, and missing-data tests.
- Create `tests/research/test_conservative_baseline.py`: fixture and real-data difference-report tests.
- Modify `tests/research/test_spec.py`, `tests/research/test_baseline.py`, `tests/research/test_cli.py`: compatibility and command coverage.
- Modify `README_FULL.md`, `STRATEGY_LOG.md`: execution-model distinction and measured v4 delta.

### Task 1: Version the conservative specification without breaking legacy

**Files:**
- Modify: `ModelStrategy/research/spec.py`
- Create: `ModelStrategy/research/configs/freeze_v4_conservative_v2.json`
- Test: `tests/research/test_spec.py`
- Test: `tests/research/test_baseline.py`

- [x] **Step 1: Write failing compatibility and conservative-spec tests**

Keep `ResearchTrade` as the legacy signal-intent type and put replayed prices/timestamps in the new `ExecutionTrade` from Task 3. Add tests proving the legacy spec still loads with an empty execution policy and the conservative policy is strict:

```python
def test_legacy_spec_has_no_execution_policy(tmp_path):
    spec = load_spec(write_spec(tmp_path, legacy_spec()))
    assert spec.execution_model == "legacy-v1"
    assert spec.execution == {}


def test_conservative_spec_requires_funding_input_and_policy(tmp_path):
    spec = load_spec(write_spec(tmp_path, conservative_spec()))
    assert spec.execution_model == "conservative-v2"
    assert spec.inputs["funding_rates"].as_posix() == "btc/btc_funding_rate.csv"
    assert spec.execution["mark_level"] == "K_60M"


def test_conservative_spec_rejects_unknown_execution_key(tmp_path):
    value = conservative_spec()
    value["execution"]["optimistic_fill"] = True
    with pytest.raises(ValueError, match="execution keys"):
        load_spec(write_spec(tmp_path, value))
```

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_spec.py tests/research/test_baseline.py -q`

Expected: failures for the missing `ResearchSpec.execution` field and rejected `conservative-v2`.

- [x] **Step 3: Implement the compatible spec extension**

Do not modify `ResearchTrade` or the legacy cache schema. Extend `ResearchSpec` with an `execution` dictionary. `load_spec()` must accept only `legacy-v1` and `conservative-v2`. Legacy specs must keep exactly the three stage-1 inputs and no execution block. Conservative specs additionally require relative `inputs.funding_rates` and exactly these execution keys:

```json
"execution": {
  "mark_level": "K_60M",
  "mark_ms": 3600000,
  "entry_patience": 8,
  "stop_slippage": 0.0005,
  "same_bar_policy": "adverse_first",
  "funding_order": "before_close",
  "funding_interval_ms": 28800000,
  "market_gap_policy": "carry_forward",
  "max_mark_gap_intervals": 16
}
```

Create `freeze_v4_conservative_v2.json` by copying the legacy strategy/risk/conviction/splits and changing only `execution_model`, adding `inputs.funding_rates`, and the execution block above.

- [x] **Step 4: Verify GREEN and legacy stability**

Run:

```text
pytest tests/research/test_schema.py tests/research/test_spec.py tests/research/test_baseline.py -q
python -m ModelStrategy.research.cli baseline --spec ModelStrategy/research/configs/freeze_v4_legacy_v1.json --research-root C:\chanpy\research --reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json --output backtest_output/research/freeze_v4_legacy_v1.json
```

Expected: tests pass and the legacy command still reports risk `0.0075`, CAGR `0.46917167124699044`.

- [x] **Step 5: Commit**

Commit spec/config with a Lore directive that `ResearchTrade`, `legacy-v1` inputs, and reference metrics cannot change.

### Task 2: Load IS-only market and funding timelines

**Files:**
- Create: `ModelStrategy/research/market.py`
- Test: `tests/research/test_market.py`

- [x] **Step 1: Write failing market-data tests**

```python
def test_market_loader_uses_bar_end_timestamps(tmp_path):
    db = make_bar_db(tmp_path, raw_ts=1609459200000)
    series = load_market_series(db, "BTC/USDT", "K_60M", 3600000,
                                parse_utc("2021-01-01"), parse_utc("2021-01-02"))
    assert series.bars[0].ts == 1609459200 + 3600


def test_market_loader_rejects_gap_inside_required_window(tmp_path):
    series = MarketSeries("BTC/USDT", 3600, bars_at_hours(0, 1, 3))
    with pytest.raises(MarketDataError, match="gap"):
        series.require_coverage(0, 3 * 3600)


def test_mark_series_carries_forward_only_bounded_gaps():
    raw = MarketSeries("BTC/USDT", 3600, bars_at_hours(0, 1, 3))
    marked = raw.carry_forward_gaps(max_missing_intervals=2)
    assert marked.at(2 * 3600).synthetic is True
    assert marked.manifest["synthetic_bar_count"] == 1


def test_funding_loader_excludes_2026_rows_from_manifest(tmp_path):
    path = write_funding(tmp_path, [("2025-12-31T16:00:00Z", 0.001),
                                    ("2026-01-01T00:00:00Z", 0.9)])
    events, manifest = load_funding_events(path, "BTC/USDT",
                                           parse_utc("2025-01-01"), parse_utc("2026-01-01"))
    assert [event.rate for event in events] == [0.001]
    assert manifest["row_count"] == 1
```

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_market.py -q`

Expected: import failure for `ModelStrategy.research.market`.

- [x] **Step 3: Implement market values, loaders, and logical manifests**

Create immutable `MarketBar(ts, open, high, low, close, synthetic=False)`, `FundingEvent(ts, symbol, rate)`, and `MarketSeries(symbol, interval_seconds, bars)`. Validate finite OHLC, `low <= min(open, close) <= max(open, close) <= high`, strict timestamps, and exact interval continuity over required position windows. Raw coverage checks fail on gaps. `carry_forward_gaps(max_missing_intervals)` may synthesize flat, explicitly flagged mark bars only up to the configured cap; it records every gap and synthetic count in the derived manifest. SQLite loader must select raw rows whose computed end timestamp is in the half-open IS window. Funding loader must parse aware UTC timestamps, normalize `BTCUSDT` to `BTC/USDT`, select only the requested half-open window, and hash canonical selected rows rather than the whole CSV. `require_funding_coverage()` must enforce every configured 8-hour settlement in the half-open IS window.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/research/test_market.py tests/research/test_provenance.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

Record that all manifests are logical IS subsets and later funding rows cannot change them.

### Task 3: Replay entries and enforce adverse same-bar ordering

**Files:**
- Create: `ModelStrategy/research/execution.py`
- Test: `tests/research/test_execution.py`

- [x] **Step 1: Write failing execution tests**

```python
def test_maker_fill_occurs_on_first_touch_not_signal_bar():
    intent = intent_trade(open_ts=HOUR, close_ts=5 * HOUR, is_buy=True)
    outcome = replay_trade(intent, series([
        bar(HOUR, close=100, low=100),
        bar(2 * HOUR, close=102, low=101),
        bar(3 * HOUR, close=101, low=99),
    ]), patience=8, stop_slippage=0.0005)
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.fill_ts == 3 * HOUR
    assert replayed.open_price == 100
    assert replayed.entry_role == "maker"


def test_unfilled_limit_chases_at_patience_close_as_taker():
    outcome = replay_trade(intent_trade(), rising_series(), patience=2,
                           stop_slippage=0.0005)
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.fill_ts == 3 * HOUR
    assert replayed.open_price == rising_series().at(3 * HOUR).close
    assert replayed.entry_role == "taker"


def test_same_bar_entry_and_stop_uses_stop_with_adverse_slippage():
    outcome = replay_trade(long_intent(entry=100, stop=95),
                           series([bar(2 * HOUR, high=101, low=94)]),
                           patience=8, stop_slippage=0.0005)
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.close_ts == replayed.fill_ts
    assert replayed.close_price == pytest.approx(95 * (1 - 0.0005))
    assert replayed.reason == "same_bar_stop"


def test_better_than_limit_fill_is_never_assumed():
    outcome = replay_trade(long_intent(entry=100),
                           series([bar(2 * HOUR, open=98, high=101, low=97, close=99)]),
                           patience=8, stop_slippage=0.0005)
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.open_price == 100
```

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_execution.py -q`

Expected: import failure for `execution.py`.

- [x] **Step 3: Implement deterministic execution replay**

Create immutable `ExecutionTrade` with symbol, signal/fill/close timestamps, direction, fill/close prices, initial stop, actual fill-to-stop risk rate/multiplier, signal type, stack, maker/taker roles, pyramid flag, and reason. Create immutable `ReplayOutcome(status, trade)` where status is `filled` or `unfilled` and `trade` is `None` only when unfilled. `build_intent()` reconstructs signal price from the stack bar close, close price from legacy profit and direction, and initial stop from risk distance. The orchestration layer must label S1/S2 source stacks explicitly before merging because the cache itself has no stack field. `replay_trade()` requires complete raw real-bar coverage from the first bar after the signal through the earlier of original close and patience horizon; a synthetic carry-forward mark cannot hide an execution gap or participate in fills/stops. First touch fills exactly at the limit, otherwise the `patience`-th real bar closes as a taker chase. Pyramid legs fill at their signal close. If the candidate fill timestamp is after the original close, return `ReplayOutcome("unfilled", None)`; a fill exactly at the original close is valid only for an immediate same-timestamp adverse stop. On an intrabar maker fill whose bar also reaches the initial stop, force same-timestamp stop exit with adverse slippage.

- [x] **Step 4: Verify GREEN and symmetry**

Run: `pytest tests/research/test_execution.py -q`

Expected: long and mirrored short parameterizations all pass.

- [x] **Step 5: Commit**

Record the adverse-first and no-price-improvement assumptions in trailers.

### Task 4: Evaluate mark-to-market equity, fees, funding, and leverage

**Files:**
- Create: `ModelStrategy/research/conservative.py`
- Test: `tests/research/test_conservative.py`

- [x] **Step 1: Write failing portfolio tests**

```python
def test_unrealized_loss_counts_toward_drawdown_before_close():
    trade = execution_trade(open_price=100, close_price=110, fill_ts=0, close_ts=3 * DAY)
    marks = series([bar(DAY, close=80), bar(2 * DAY, close=100), bar(3 * DAY, close=110)])
    result = conservative_portfolio_eval([trade], {"BTC/USDT": marks}, [], no_fee_conf())
    assert result.total_return > 0
    assert result.max_drawdown > 0


@pytest.mark.parametrize("is_buy,rate,expected_sign", [(True, 0.001, -1), (False, 0.001, 1)])
def test_funding_payment_direction(is_buy, rate, expected_sign):
    result = conservative_portfolio_eval(
        [execution_trade(is_buy=is_buy)], {"BTC/USDT": flat_marks()},
        [FundingEvent(HOUR, "BTC/USDT", rate)], no_fee_conf())
    assert math.copysign(1, result.funding_pnl) == expected_sign


def test_entry_fee_reduces_equity_immediately():
    result = conservative_portfolio_eval([flat_trade(entry_role="maker")],
                                         {"BTC/USDT": flat_marks()}, [], fee_conf())
    entry_point = next(point for point in result.curve if point.kind == "open")
    assert entry_point.equity < 1.0


def test_missing_mark_inside_holding_window_fails():
    with pytest.raises(MarketDataError, match="gap"):
        conservative_portfolio_eval([execution_trade()], {"BTC/USDT": gapped_marks()}, [], no_fee_conf())
```

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_conservative.py -q`

Expected: import failure for `conservative.py`.

- [x] **Step 3: Implement the event-driven conservative evaluator**

Create immutable `EquityPoint(ts, kind, equity)` and `ConservativeResult(total_return, cagr, max_drawdown, calmar, fees, funding_pnl, curve, accepted_trades, skipped_trades)`. Maintain realized cash, position quantity/notional, latest marks, fees, and funding PnL. At each timestamp first refresh existing positions to that timestamp's mark without recording a curve point; then process funding, close, atomic same-bar round trip, and open; finally apply the recorded mark event so positions opened at that timestamp are also marked. Funding therefore remains before close, while both funding and entry sizing use the current timestamp price. Size entries from current marked equity; apply concurrency, total leverage, and per-position leverage caps after accounting for immediate entry fees. Deduct entry fees at fill, realize quantity-based price PnL and exit-value fee at close, and apply `-direction * marked_position_value * funding_rate` at settlement. Append equity points for every effective event and every recorded mark. Maximum drawdown uses the complete marked curve, including explicitly synthesized carry-forward marks, not only closes. Reject any remaining coverage gap, non-finite equity, unknown fee roles, duplicate trades, and non-positive equity. A trade rejected by concurrency or leverage is counted in `skipped_trades` and never receives later close/funding events.

- [x] **Step 4: Verify GREEN and legacy isolation**

Run: `pytest tests/research/test_conservative.py tests/test_portfolio.py tests/research/test_baseline.py -q`

Expected: new tests pass and all legacy portfolio/baseline tests remain green.

- [x] **Step 5: Commit**

Record event ordering and funding semantics in the Lore directive.

### Task 5: Generate and freeze the real v4 difference report

**Files:**
- Create: `ModelStrategy/research/conservative_baseline.py`
- Create: `ModelStrategy/research/baselines/freeze_v4_conservative_v2.json`
- Modify: `ModelStrategy/research/cli.py`
- Test: `tests/research/test_conservative_baseline.py`
- Test: `tests/research/test_cli.py`
- Modify: `README_FULL.md`
- Modify: `STRATEGY_LOG.md`

- [x] **Step 1: Write failing calibration/report/CLI tests**

Fixture tests must prove the report contains both models, metric deltas, fee/funding totals, fill counts, skipped entries, spec/input hashes, and no OOS rows. CLI tests run:

```text
python -m ModelStrategy.research.cli compare --spec <conservative-spec> --research-root <fixture> --market-data-root <fixture> --legacy-reference <legacy.json> --output <report.json>
```

and assert atomic success plus no output on a conservative-reference mismatch.

- [x] **Step 2: Verify RED**

Run: `pytest tests/research/test_conservative_baseline.py tests/research/test_cli.py -q`

Expected: missing conservative baseline and `compare` command failures.

- [x] **Step 3: Implement calibration and difference reporting**

Load S1/S2 intents and label their source stacks, build conservative execution trades from stack-specific bars, discard only explicit `unfilled` outcomes, recompute conviction on actual fill timestamps, load hourly marks and funding, then evaluate the same frozen risk grid. Split membership uses actual `fill_ts` in half-open intervals; trades filled before a split but closed inside it are not re-attributed. Select the highest risk whose full/split worst DD is at most 25%. Emit:

```json
{
  "execution_model": "conservative-v2",
  "legacy_reference": {"risk_pct": 0.0075, "is_2125": {}},
  "conservative": {"risk_pct": 0.0, "is_2125": {}, "fees": 0.0, "funding_pnl": 0.0},
  "delta": {"cagr": 0.0, "max_drawdown": 0.0, "calmar": 0.0},
  "execution": {"maker_fills": 0, "taker_fills": 0, "same_bar_stops": 0, "unfilled": 0},
  "inputs": {},
  "provenance": {}
}
```

The real values replace the zeros. Do not compare conservative metrics to the legacy reference as equality; freeze the measured conservative result only after the real command completes.

- [x] **Step 4: Run real IS comparison and create the tracked reference**

Run with `C:\chanpy\research` and `C:\chanpy\data`. Inspect the report for boundary end `2026-01-01`, finite metrics, hourly coverage, the exact gap/synthetic-bar manifest, and exact selected-input manifests. Copy only the compact result/assumption section into `freeze_v4_conservative_v2.json`, then rerun the command with `--conservative-reference` so drift becomes a hard failure.

- [x] **Step 5: Document and run the stage-2 gate**

Update docs with measured deltas and limitations. Run:

```text
pytest tests/research -q
pytest -q -m "not network"
python -m compileall -q ModelStrategy/research tests/research
git diff --check
```

Expected: all tests pass; legacy CLI still exactly matches; conservative CLI matches its new reference; no 2026 strategy result or live order is produced. Commit with complete verification trailers.

## Stage-2 completion evidence

1. `freeze_v4_legacy_v1.json` and its CLI result remain unchanged.
2. Every conservative execution rule has a synthetic counterexample test that failed before implementation.
3. The real report includes marked drawdown, immediate fees, funding PnL, actual maker fill timestamps, same-bar stop count, and unfilled count.
4. Input manifests select only 2021–2025 logical rows from both SQLite and funding CSV; all carry-forward mark bars are flagged and counted, and none participate in execution replay.
5. The tracked conservative reference is reproduced by a clean command and the offline full suite passes.
