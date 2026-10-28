"""Exact, source-bound *observed interval* checks, never an admission certificate.

REST snapshots are intervals, not atomic instants. Events inside either snapshot
interval are ambiguous. Fractions preserve pooled entry prices without inventing
an exchange rounding tolerance. Native funding without a leg remains account-only.
The database wrapper supplies freshly verified histories and scan associations.
"""
import hashlib
from decimal import Decimal, DecimalException
from fractions import Fraction

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import verify_account_context
from .AccountSources import verify_account_snapshot, verify_wallet_scan
from .ExecutionReconcile import _order_ids, build_execution_ownership


SCHEMA = "chan-account-reconciliation-v1"


def _fail():
    raise CChanException("账户区间对账证据损坏或身份不完整，禁止新风险", ErrCode.LIST_ORDER_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _number(value):
    if type(value) not in (str, int, float):
        _fail()
    value = Decimal(str(value))
    if not value.is_finite() or (value and abs(value.adjusted()) > 100) or len(value.as_tuple().digits) > 50:
        _fail()
    return Fraction(value)


def _ratio(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _key(position):
    return (position["instrument"], position["position_side"], position["margin_mode"])


def _covered(windows, start, end):
    cursor = start
    for begin, finish in sorted(windows):
        if begin > cursor:
            break
        cursor = max(cursor, finish)
    return cursor >= end


def _unique(rows, key, issue):
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result and canonical_bytes(result[identity]) != canonical_bytes(row):
            issue("source_identity_conflict", identity=str(identity), incomplete=True)
        else:
            result[identity] = row
    return list(result.values())


def _latest(events, boundary, field, issue, identity):
    candidates = [e for e in events if e["observed_ms"] <= boundary]
    if not candidates:
        return Fraction(0)
    at = max(e["observed_ms"] for e in candidates)
    # Ordinal orders one attempt, not two independent attempts at the same ms.
    latest = {}
    for attempt, event in ((e["attempt_key"], e) for e in candidates if e["observed_ms"] == at):
        if attempt not in latest or event["ordinal"] > latest[attempt]["ordinal"]:
            latest[attempt] = event
    values = {_number(e["state"][field] or 0) for e in latest.values()}
    if len(values) != 1:
        issue("ambiguous_db_clock", identity=identity, incomplete=True)
        return Fraction(0)
    return next(iter(values))


def _native_positions(snapshot, issue, endpoint):
    positions = {}
    for row in snapshot["positions"]:
        key = _key(row)
        if key in positions:
            issue("ambiguous_native_leg", endpoint=endpoint, leg=list(key), incomplete=True)
        positions[key] = row
        quantity, entry, mark, upl = (_number(row[k] or 0) for k in ("quantity", "entry_price", "mark_price", "unrealized_pnl"))
        sign = -1 if row["direction"] == "short" else 1
        if sign*(mark-entry)*quantity != upl:
            issue("position_unrealized_difference", endpoint=endpoint, leg=list(key))
        if (snapshot["account_context"]["venue"] == "binance"
                and (row["reported_notional"] is None or _number(row["reported_notional"]) != sign*quantity*mark)):
            issue("position_notional_difference", endpoint=endpoint, leg=list(key))
        if row["margin_mode"] == "isolated" and _number(row["isolated_balance"] or 0):
            issue("isolated_position_channel_unproven", endpoint=endpoint, leg=list(key), incomplete=True)
    if snapshot["unsupported_positions"]:
        issue("unsupported_positions", endpoint=endpoint, incomplete=True)
    by_currency = {}
    for row in positions.values():
        by_currency[row["currency"]] = by_currency.get(row["currency"], Fraction(0))+_number(row["unrealized_pnl"])
    for asset in snapshot["assets"]:
        currency = asset["currency"]
        if asset["unrealized_pnl"] is None:
            issue("asset_unrealized_missing", endpoint=endpoint, currency=currency, incomplete=True)
        elif _number(asset["unrealized_pnl"]) != by_currency.pop(currency, Fraction(0)):
            issue("asset_unrealized_difference", endpoint=endpoint, currency=currency)
        # Do not equate OKX USD IMR, or borrowing/isolated equity, to USDT cash.
        if any(_number(asset[k] or 0) for k in ("liability", "reported_interest", "isolated_equity")):
            issue("asset_equity_channels_unproven", endpoint=endpoint, currency=currency, incomplete=True)
        if asset["equity"] is None:
            issue("asset_equity_missing", endpoint=endpoint, currency=currency, incomplete=True)
        elif asset["unrealized_pnl"] is not None and _number(asset["cash_balance"])+_number(asset["unrealized_pnl"]) != _number(asset["equity"]):
            issue("asset_equity_difference", endpoint=endpoint, currency=currency)
    if by_currency:
        issue("position_asset_missing", endpoint=endpoint, incomplete=True)
    totals = snapshot["reported_totals"]
    if snapshot["account_context"]["venue"] == "binance" and totals["currency"] == "USDT":
        usdt = next((a for a in snapshot["assets"] if a["currency"] == "USDT"), None)
        for total_field, asset_field in (("wallet_balance", "cash_balance"), ("unrealized_pnl", "unrealized_pnl"), ("equity", "equity")):
            if usdt is None or usdt[asset_field] is None or totals[total_field] is None:
                issue("native_total_missing", endpoint=endpoint, field=total_field, incomplete=True)
            elif _number(totals[total_field]) != _number(usdt[asset_field]):
                issue("native_total_difference", endpoint=endpoint, field=total_field)
    if snapshot["account_context"]["venue"] == "binance":
        risk = {(p["instrument_id"], p["position_side"]): p for p in positions.values()}
        independent = {(p["instrument_id"], p["position_side"]): p for p in snapshot["native_account_positions"]}
        for key in sorted(set(risk) | set(independent)):
            left, right = risk.get(key), independent.get(key)
            q = Fraction(0) if left is None else _number(left["quantity"])*(-1 if left["direction"] == "short" else 1)
            if right is None or q != _number(right["signed_quantity"]) or (left is not None and _number(left["unrealized_pnl"]) != _number(right["unrealized_pnl"])):
                issue("native_account_position_difference", endpoint=endpoint, leg=list(key))
    return positions


def _cash_components(facts, wallet, venue, issue):
    used = set()
    for instrument, fact, _ in facts:
        if venue == "binance":
            candidates = [w for w in wallet if w["instrument_id"] == instrument and w["trade_id"] == fact["trade_id"]
                and w["native_type"] in {"COMMISSION", "REALIZED_PNL"}]
            fee = sum((_number(w["account_cash_delta"]) for w in candidates if w["native_type"] == "COMMISSION" and w["currency"] == fact["fee_currency"]), Fraction(0))
            pnl = sum((_number(w["account_cash_delta"]) for w in candidates if w["native_type"] == "REALIZED_PNL" and w["currency"] == fact["pnl_currency"]), Fraction(0))
        else:
            candidates = [w for w in wallet if w["source_id"] == fact["source_id"] and w["instrument_id"] == instrument
                and w["order_id"] == fact["order_id"] and w["trade_id"] == fact["trade_id"] and w["native_type"] == "2"
                and w["currency"] == fact["fee_currency"] == fact["pnl_currency"]]
            fee = sum((_number(w["fee_cash_delta"]) for w in candidates), Fraction(0))
            pnl = sum((_number(w["reported_pnl"]) for w in candidates), Fraction(0))
            if len(candidates) != 1:
                issue("trade_cash_source_missing", source_id=fact["source_id"], incomplete=True)
            for row in candidates:
                if row["raw"].get("mgnMode") != "cross" or _number(row["position_cash_delta"] or 0) or _number(row["reported_interest"] or 0):
                    issue("trade_cash_channels_unproven", source_id=row["source_id"], incomplete=True)
                elif _number(row["account_cash_delta"]) != _number(row["fee_cash_delta"])+_number(row["reported_pnl"]):
                    issue("trade_cash_delta_difference", source_id=row["source_id"])
        if fee != _number(fact["fee_cash_delta"]) or pnl != _number(fact["realized_pnl"]):
            issue("trade_cash_component_difference", source_id=fact["source_id"])
        used.update(w["source_id"] for w in candidates)
    for row in wallet:
        if row["native_type"] in ({"COMMISSION", "REALIZED_PNL"} if venue == "binance" else {"2"}) and row["source_id"] not in used:
            issue("unowned_trade_cashflow", source_id=row["source_id"], incomplete=True)


def _build(before, after, wallets, executions, histories, projections, *, pending_validation=None, client_roots=()):
    verify_account_snapshot(before)
    verify_account_snapshot(after)
    first, last = before["payload"], after["payload"]
    account = first["account_context"]
    if (canonical_bytes(account) != canonical_bytes(last["account_context"]) or first["account_domain"] != last["account_domain"]
            or canonical_bytes(first["markets"]) != canonical_bytes(last["markets"]) or first["finished_ms"] >= last["started_ms"]):
        _fail()
    issues = []

    def issue(reason, *, incomplete=False, **details):
        issues.append({"reason": reason, "severity": "incomplete" if incomplete else "mismatch", **details})

    qualified, terminal_qualified = set(), set()
    if pending_validation is not None:
        observed = pending_validation["payload"]
        qualified = {tuple(row["attempt"][key] for key in ("trade_table", "record_id", "phase", "attempt", "client_order_id"))
                     for row in observed["orders"] if row["status"] == "owned"}
        terminal_qualified = {tuple(row["attempt"][key] for key in ("trade_table", "record_id", "phase", "attempt", "client_order_id"))
                              for row in observed.get("terminal_observations", ())}
        for row in observed["issues"]:
            issue("native_pending_"+row["reason"], incomplete=True, observation=row)

    start, end = first["started_ms"], last["finished_ms"]+1
    low, high = first["finished_ms"], last["started_ms"]

    def during(at):
        if type(at) is not int:
            issue("missing_event_clock", incomplete=True)
            return False
        if first["started_ms"] <= at <= low or high <= at <= last["finished_ms"]:
            issue("event_inside_snapshot_interval", at_ms=at, incomplete=True)
        return low < at < high

    wallet_windows, cash = [], []
    for document in wallets:
        verify_wallet_scan(document)
        payload = document["payload"]
        if canonical_bytes(payload["account_context"]) != canonical_bytes(account) or payload["account_domain"] != first["account_domain"]:
            _fail()
        if payload["started_ms"] < last["finished_ms"]:
            issue("wallet_observed_before_endpoint", incomplete=True)
        wallet_windows.append((payload["start_ms"], payload["end_ms"]))
        cash.extend(payload["facts"])
    if not _covered(wallet_windows, start, end):
        issue("wallet_window_missing", incomplete=True)
    cash = [f for f in _unique(cash, lambda f: f["source_id"], issue) if start <= f["timestamp_ms"] < end and during(f["timestamp_ms"])]
    for row in cash:
        if _number(row["position_cash_delta"] or 0):
            issue("position_cash_channel_unallocated", source_id=row["source_id"], incomplete=True)
    assets_before = {a["currency"]: a for a in first["assets"]}
    assets_after = {a["currency"]: a for a in last["assets"]}
    wallet_results = []
    for currency in sorted(set(assets_before) | set(assets_after) | {f["currency"] for f in cash}):
        left, right = assets_before.get(currency), assets_after.get(currency)
        if left is None or right is None:
            issue("asset_endpoint_missing", currency=currency, incomplete=True)
            continue
        flows = sorted((f for f in cash if f["currency"] == currency), key=lambda f: (f["timestamp_ms"], int(f["native_id"])))
        running = _number(left["cash_balance"])
        for fact in flows:
            running += _number(fact["account_cash_delta"])
            if fact["balance_after"] is not None and running != _number(fact["balance_after"]):
                issue("native_cash_balance_chain_difference", source_id=fact["source_id"], currency=currency)
        difference = running-_number(right["cash_balance"])
        if difference:
            issue("wallet_difference", currency=currency)
        wallet_results.append({"currency": currency, "before": left["cash_balance"], "after": right["cash_balance"],
            "cash_delta": _ratio(running-_number(left["cash_balance"])), "difference": _ratio(difference)})

    positions_before = _native_positions(first, issue, "before")
    positions_after = _native_positions(last, issue, "after")
    attempts, record_events, record_open, other_accounts = {}, {}, {}, set()
    references = []
    from .OrderAudit import _history_header
    for history in histories:
        if canonical_bytes({key: history[key] for key in ("schema", "coverage", "economics_complete")}) != canonical_bytes(_history_header(history["attempts"])):
            _fail()
        for attempt in history["attempts"]:
            identity, contract = attempt["identity"], attempt["identity"]["order_contract"]
            if not isinstance(contract, dict) or contract.get("schema") not in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}:
                issue("unidentified_attempt", incomplete=True)
                continue
            if contract["schema"] == "chan-native-client-order-v1":
                from .NativeOrderTransition import _client_reference
                references.append(_client_reference(attempt, client_roots))
            verify_account_context(contract["account_context"])
            if canonical_bytes(contract["account_context"]) != canonical_bytes(account):
                native_keys = ("venue", "mode", "identifier_kind", "identifier_sha256")
                if all(contract["account_context"][k] == account[k] for k in native_keys):
                    issue("historical_account_environment_drift", incomplete=True)
                elif identity["phase"] == "open":
                    other_accounts.add((identity["trade_table"], identity["record_id"]))
                continue
            if (attempt["origin"] != "new_intent" or identity["contract_complete"] is not True or history["gaps"]
                    or _sha(contract) != identity["contract_sha256"]
                    or _sha({k: v for k, v in contract.items() if k != "contract_id"}) != contract["contract_id"]):
                issue("incomplete_attempt_history", incomplete=True)
            ref = tuple(identity[k] for k in ("trade_table", "record_id", "phase", "attempt", "client_order_id"))
            if ref in attempts:
                _fail()
            attempts[ref] = attempt
            if attempt["events"][-1]["state"]["order_status"] not in {"closed", "canceled", "rejected"} and ref not in qualified:
                issue("unresolved_attempt", identity=list(ref), incomplete=True)
            if (contract["schema"] == "chan-native-client-order-v1" and ref not in terminal_qualified
                    and attempt["events"][-1]["state"]["order_status"] in {"closed", "canceled", "rejected"}):
                issue("client_terminal_not_observed", identity=list(ref), incomplete=True)
            clocks = [e["observed_ms"] for e in attempt["events"]]
            if clocks != sorted(clocks):
                issue("nonmonotonic_journal_clock", identity=list(ref), incomplete=True)
            record = ref[:2]
            if identity["phase"] == "open":
                if record in record_open:
                    issue("multiple_open_attempts", identity=list(record), incomplete=True)
                record_open[record] = identity
            for event in attempt["events"]:
                if type(event["observed_ms"]) is not int:
                    _fail()
                record_events.setdefault(record, []).append({**event, "attempt_key": ref})
                if event["observed_ms"] >= high:
                    issue("db_event_at_or_after_endpoint", identity=list(record), incomplete=True)

    if pending_validation is not None:
        # A terminal zero-fill claim can still conflict with a real native
        # order. Do not select a best client-id match in this new version.
        # Binance identifiers are per market, not globally unique.
        by_order = {}
        for ref, attempt in attempts.items():
            instrument = attempt["identity"]["order_contract"]["market"]["id"]
            for native_id in _order_ids(attempt):
                by_order.setdefault((instrument, native_id), []).append(list(ref))
        for key, identities in sorted(by_order.items()):
            if len(identities) > 1:
                issue("ambiguous_historical_order_id", incomplete=True, native_order=list(key), attempts=identities)

    all_facts, funding_facts, windows = [], [], {}
    market_map = {m["symbol"]: m for m in first["markets"]}
    for source in executions:
        receipt = source["receipt"]
        if canonical_bytes(source["account_context"]) != canonical_bytes(account):
            _fail()
        payload = receipt["payload"]
        symbol = payload["market"]["symbol"]
        if symbol not in market_map or canonical_bytes(payload["market"]) != canonical_bytes(market_map[symbol]):
            _fail()
        if type(source["observed_ms"]) is not int or source["observed_ms"] < last["finished_ms"]:
            issue("execution_observed_before_endpoint", instrument=symbol, incomplete=True)
        ownership = build_execution_ownership(receipt, account, histories, client_roots=client_roots)["payload"]["trades"]
        owned = {r["source_id"]: r for r in ownership}
        windows.setdefault(symbol, []).append((payload["start_ms"], payload["end_ms"]))
        for fact in payload["facts"]:
            if not start <= fact["source_ms"] < end:
                if fact["timestamp_ms"] is not None and start <= fact["timestamp_ms"] < end:
                    issue("late_execution_source_clock", source_id=fact["source_id"], incomplete=True)
                continue
            if not during(fact["timestamp_ms"]):
                issue("execution_clock_outside_interval", source_id=fact["source_id"], incomplete=True)
                continue
            if fact["kind"] == "funding":
                funding_facts.append((market_map[symbol]["id"], fact))
            elif owned[fact["source_id"]]["status"] != "owned":
                issue("unowned_execution", source_id=fact["source_id"], ownership_reason=owned[fact["source_id"]]["reason"], incomplete=True)
            else:
                all_facts.append({"instrument": symbol, "instrument_id": market_map[symbol]["id"], "fact": fact, "owner": owned[fact["source_id"]]["attempt"]})
    for symbol in market_map:
        if not _covered(windows.get(symbol, []), start, end):
            issue("execution_window_missing", instrument=symbol, incomplete=True)
    all_facts = _unique(all_facts, lambda r: (r["instrument"], r["fact"]["source_id"]), issue)
    funding_facts = _unique([{"instrument": i, "fact": f} for i, f in funding_facts], lambda r: (r["instrument"], r["fact"]["source_id"]), issue)
    used_funding = set()
    venue = account["venue"]
    for item in funding_facts:
        fact = item["fact"]
        source_id = "FUNDING_FEE:"+fact["source_id"] if venue == "binance" else fact["source_id"]
        matched = [w for w in cash if w["source_id"] == source_id and w["instrument_id"] == item["instrument"] and w["currency"] == fact["currency"]]
        different = (len(matched) != 1 or matched[0]["timestamp_ms"] != fact["source_ms"]
            or _number(matched[0]["account_cash_delta"]) != _number(fact["wallet_cash_delta"] if venue == "okx" else fact["cash_delta"]))
        if not different and venue == "okx":
            different = any(_number(matched[0][wallet_field] or 0) != _number(fact[source_field] or 0)
                for wallet_field, source_field in (("reported_pnl", "cash_delta"), ("fee_cash_delta", "fee_cash_delta"), ("position_cash_delta", "position_cash_delta")))
        if different:
            issue("funding_cash_source_difference", source_id=source_id, incomplete=True)
        else:
            used_funding.add(source_id)
    for row in cash:
        if row["native_type"] == ("FUNDING_FEE" if venue == "binance" else "8") and row["source_id"] not in used_funding:
            issue("funding_execution_source_missing", source_id=row["source_id"], incomplete=True)
    _cash_components([(r["instrument_id"], r["fact"], r["owner"]) for r in all_facts], cash, venue, issue)

    book = {k: {"q": _number(p["quantity"]), "entry": _number(p["entry_price"] or 0),
        "sign": -1 if p["direction"] == "short" else 1} for k, p in positions_before.items()}
    totals, notionals = {}, {}
    ordered = sorted(all_facts, key=lambda r: (r["fact"]["timestamp_ms"], int(r["fact"]["trade_id"])))
    for row in ordered:
        fact, owner = row["fact"], row["owner"]
        ref = tuple(owner[k] for k in ("trade_table", "record_id", "phase", "attempt", "client_order_id"))
        attempt = attempts[ref]
        identity, contract = attempt["identity"], attempt["identity"]["order_contract"]
        key = (row["instrument"], fact["position_side"], contract["execution"]["margin_mode"])
        leg = book.setdefault(key, {"q": Fraction(0), "entry": Fraction(0), "sign": 1 if identity["is_buy"] else -1})
        quantity, price, realized = _number(fact["quantity"]), _number(fact["price"]), Fraction(0)
        if owner["phase"] == "open":
            sign = 1 if identity["is_buy"] else -1
            if leg["q"] and leg["sign"] != sign:
                issue("opposing_one_way_risk", leg=list(key), incomplete=True)
            leg["entry"] = (leg["q"]*leg["entry"]+quantity*price)/(leg["q"]+quantity)
            leg["q"] += quantity
            leg["sign"] = sign
        else:
            if quantity > leg["q"]:
                issue("close_exceeds_native_leg", source_id=fact["source_id"], incomplete=True)
            realized = leg["sign"]*(price-leg["entry"])*quantity
            leg["q"] -= quantity
            if not leg["q"]:
                leg["entry"] = Fraction(0)
        if realized != _number(fact["realized_pnl"]):
            issue("execution_realized_difference", source_id=fact["source_id"])
        totals[ref] = totals.get(ref, Fraction(0))+quantity
        notionals[ref] = notionals.get(ref, Fraction(0))+quantity*price
    for ref, attempt in attempts.items():
        events = [{**e, "attempt_key": ref} for e in attempt["events"]]
        before_qty = _latest(events, start, "filled_qty", issue, list(ref))
        after_qty = _latest(events, last["finished_ms"], "filled_qty", issue, list(ref))
        if after_qty-before_qty != totals.get(ref, Fraction(0)):
            issue("attempt_fill_quantity_difference", identity=list(ref))
        if ref in terminal_qualified:
            terminal = next(event["native_order_observation"]["payload"] for event in reversed(attempt["events"])
                            if event["kind"] == "native_terminal_observation")
            if (totals.get(ref, Fraction(0)) == _number(terminal["filled_base_quantity"])
                    and notionals.get(ref, Fraction(0)) != _number(terminal["raw"]["cumQuote"])):
                issue("native_terminal_notional_difference", identity=list(ref))

    db_before, db_after = {}, {}
    projection_map = {(p["trade_table"], p["record_id"]): p for p in projections}
    if len(projection_map) != len(projections):
        _fail()
    for ref, projection in projection_map.items():
        identity = record_open.get(ref)
        if identity is None:
            if ref in other_accounts:
                continue
            if _number(projection["current_qty"]):
                issue("unidentified_db_position", identity=list(ref), incomplete=True)
            continue
        contract = identity["order_contract"]
        key = (identity["instrument"], identity["position_side"], contract["execution"]["margin_mode"])
        events = record_events[ref]
        before_qty = _latest(events, start, "current_qty", issue, list(ref))
        after_qty = _latest(events, last["finished_ms"], "current_qty", issue, list(ref))
        if after_qty != _number(projection["current_qty"]) or projection["instrument"] != key[0] or projection["position_side"] != key[1] or bool(projection["is_buy"]) != bool(identity["is_buy"]):
            issue("db_quantity_difference", identity=list(ref))
        db_before[key] = db_before.get(key, Fraction(0))+before_qty
        db_after[key] = db_after.get(key, Fraction(0))+after_qty
    if set(record_open)-set(projection_map):
        issue("db_projection_missing", incomplete=True)
    for endpoint, quantities, native in (("before", db_before, positions_before), ("after", db_after, positions_after)):
        for key in sorted(set(quantities) | set(native)):
            native_qty = _number(native[key]["quantity"]) if key in native else Fraction(0)
            if quantities.get(key, Fraction(0)) != native_qty:
                issue("db_native_quantity_difference", endpoint=endpoint, leg=list(key))
    results = []
    for key in sorted(set(book) | set(positions_after)):
        expected = book.get(key, {"q": Fraction(0), "entry": Fraction(0), "sign": 1})
        native = positions_after.get(key)
        if expected["q"] != (_number(native["quantity"]) if native else 0):
            issue("position_quantity_difference", leg=list(key))
        if native is not None and _number(native["quantity"]):
            if expected["entry"] != _number(native["entry_price"]):
                issue("entry_price_difference", leg=list(key))
            if expected["sign"] != (-1 if native["direction"] == "short" else 1):
                issue("position_direction_difference", leg=list(key))
        upl = expected["sign"]*((_number(native["mark_price"] or 0) if native else 0)-expected["entry"])*expected["q"]
        if native is not None and upl != _number(native["unrealized_pnl"]):
            issue("position_unrealized_difference", endpoint="rebuilt", leg=list(key))
        results.append({"leg": list(key), "quantity": _ratio(expected["q"]), "entry_price": _ratio(expected["entry"]), "unrealized_pnl": _ratio(upl)})
    issues = sorted({canonical_bytes(r): r for r in issues}.values(), key=canonical_bytes)
    inputs = {"before": before, "after": after, "wallets": wallets, "executions": executions,
              "histories": histories, "projections": projections}
    if pending_validation is not None:
        inputs["pending_validation"] = pending_validation
    if references:
        inputs["client_roots"] = client_roots
    payload = {"account_context": account, "start_ms": start, "end_ms": end,
        "coverage": "observed_account_interval" if pending_validation is None else "observed_account_interval_with_native_pending",
        "economics_complete": False,
        "status": "incomplete" if any(r["severity"] == "incomplete" for r in issues) else "mismatch" if issues else "matched_observations",
        "input_sha256": _sha(inputs),
        "wallets": wallet_results, "positions": results, "issues": issues,
        "disclosures": {"funding_allocation": "account_only_native_leg_missing", "mark_generation_clock": "unknown",
            "position_margin_currency": "USDT" if venue == "binance" else "USD", "native_rounding_tolerance": "none",
            "usd_totals": "retained_not_converted_or_added_to_settlement_cash",
            "completeness": "provided_observations_only_not_trading_admission"}}
    if pending_validation is not None:
        payload["pending"] = pending_validation
    schema = SCHEMA if pending_validation is None else "chan-account-reconciliation-pending-v2"
    if references:
        payload["client_order_references"] = references
        schema = "chan-account-reconciliation-v2" if pending_validation is None else "chan-account-reconciliation-pending-v3"
    if terminal_qualified:
        schema = "chan-account-reconciliation-pending-v4"
    return {"schema": schema,
            "payload": payload, "payload_sha256": _sha(payload)}


def build_account_reconciliation(*, before, after, wallets, executions, histories, projections, client_roots=()):
    """Inputs from a single verified DB snapshot; no network, writes or unlock."""
    try:
        return _build(before, after, wallets, executions, histories, projections, client_roots=client_roots)
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException, ZeroDivisionError):
        _fail()


def build_account_reconciliation_with_pending(*, before, after, wallets, executions, histories, projections, pending_orders, client_roots=()):
    """New observational version; qualify only from raw pending + same ledger.

    The original v1 builder never takes this argument or returns this schema.
    There is no caller-supplied matched report or set of exempt attempts.
    """
    from .NativePendingOrders import verify_native_pending_orders
    from .NativePendingOwnership import SCHEMA as PENDING_SCHEMA, CLIENT_SCHEMA, TERMINAL_SCHEMA, _build as pending_ownership
    from .ExecutionFacts import _MONEY, _market
    from decimal import localcontext
    try:
        verify_native_pending_orders(pending_orders)
        source = pending_orders["payload"]
        if (canonical_bytes(source["account_context"]) != canonical_bytes(after["payload"]["account_context"])
                or not before["payload"]["finished_ms"] < source["started_ms"] <= source["finished_ms"] < after["payload"]["started_ms"]
                or canonical_bytes(sorted((_market(row) for row in source["markets"]), key=lambda row: row["id"]))
                   != canonical_bytes(sorted(after["payload"]["markets"], key=lambda row: row["id"]))):
            _fail()
        with localcontext(_MONEY):
            payload = pending_ownership(source, {"histories": histories, "projections": projections}, client_roots=client_roots)
        pending = {"schema": TERMINAL_SCHEMA if "terminal_observations" in payload else CLIENT_SCHEMA if "client_order_references" in payload else PENDING_SCHEMA,
                   "payload": payload, "payload_sha256": _sha(payload)}
        return _build(before, after, wallets, executions, histories, projections, pending_validation=pending, client_roots=client_roots)
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException, ZeroDivisionError):
        _fail()
