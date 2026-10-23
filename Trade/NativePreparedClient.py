"""Explicit cold SDK initialization from owned native reads, never a send gate.

Only a newly created client may receive its initial market cache. An existing
client is never refreshed, and fresh startup GETs never renew an old intent.
"""
import copy

from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativePreparation as Prepare
from . import NativePreparedIntent as Prepared
from . import NativeInstrumentCurrent as Instrument
from . import NativeOrderBoundary as Boundary
from . import NativeOrderTransition as Transition
from .AccountIdentity import observe_account_context
from .AccountRiskStore import _sha, risk_state


def initialize_native_prepared_client(engine, record_id, *, instrument_max_age_ms, instrument_max_observation_span_ms):
    """Build a new SDK cache using the original parser and native settings.

    No caller client/receipt/cache, prepare, order write or permission result.
    A persisted intent additionally retains its original L1 and source clocks.
    """
    client, account, source_started, chan = None, None, False, None
    try:
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy
        Prepared._budget(instrument_max_age_ms)
        Prepared._budget(instrument_max_observation_span_ms)
        if (type(engine) is not CCCXTTradeEngine or engine.exchange is not None
                or type(record_id) is not int or record_id <= 0
                or type(engine.opening_inputs) is not COpeningInputs or type(engine.safety_policy) is not TradingSafetyPolicy):
            Prepared._fail()
        chan, guard, policy = engine.chan_db, engine.opening_inputs, engine.safety_policy
        database = Boundary._database(chan)
        connection, table, clock = database.conn, chan.table, guard.now_ms
        Boundary._same_database(chan, database, connection, table, owned=False)
        implementation, started = Prepared._implementation(), utc_now_ms()
        configuration = canonical_bytes(engine.ccxt_conf)
        if type(started) is not int or not 0 <= started < 2**63:
            Prepared._fail()

        def owners(*, owned=False):
            Boundary._same_database(chan, database, connection, table, owned=owned)
            if (engine.chan_db is not chan or engine.exchange is not client or engine.opening_inputs is not guard
                    or engine.safety_policy is not policy or guard.now_ms is not clock
                    or canonical_bytes(engine.ccxt_conf) != configuration or Prepared._implementation() != implementation):
                Prepared._fail()
            if client is not None and any(getattr(client, target, None) != (engine.ccxt_conf.get(key) or None)
                                          for target, key in (("apiKey", "api_key"), ("secret", "secret"), ("password", "password"))):
                Prepared._fail()

        with database.transaction():
            owners(owned=True)
            record = chan.get_record(record_id)
            if record is None:
                Prepared._fail()
            document = None
            if record["status"] != "signal":
                document = Transition._read(chan, record)
                b = document["payload"]["root"]["preparation"]
                if (document["schema"] != Transition.PREPARED_DOCUMENT_SCHEMA or document["payload"]["stage"] != "intent"
                        or b["schema"] != Prepared.BINDING_SCHEMA or b["implementation_sha256"] != implementation):
                    Prepared._fail()
                Transition._current(chan, document)
                Prepared._windows(chan, b, document["payload"]["root"]["boundary"])
                account = b["identity"]["payload"]["order_contract"]["account_context"]
            expected_hash = None if document is None else document["payload"]["after_record_sha256"]
            price = None if document is None else b["identity"]["payload"]["request"]["price"]

            def local_view():
                runtime = Prepare._selected_runtime(engine, guard, policy)
                owners(owned=True)
                return Prepare._local_prepare_view(engine, guard, policy, chan, database, table, record_id,
                    price, runtime, lambda: owners(owned=True), persisted_record_sha256=expected_hash)

            observed, _ = local_view()
            local = canonical_bytes(Prepare._stable_local_view(observed))
            records, prefix = _sha(Transition._records(chan)), Transition._prefix(database)
            codes = observed["scope"]["code_list"]
            if account is not None:
                chan.assert_account_new_risk_allowed(account)
        owners()
        source_started = True
        client = engine.get_exchange()
        owners()
        reference, ccxt = Instrument.source._reference(client.id, engine.mode)
        if type(client) is not type(reference) or client.markets or client.markets_by_id:
            Prepared._fail()
        Instrument._original_method(client, "parse_market", reference.parse_market.__func__)
        Instrument._original_method(client, "set_markets", ccxt.Exchange.set_markets)
        source = Instrument.source.collect_native_instrument_evidence(client, codes, mode=engine.mode)
        owners()
        p = source["payload"]
        # Only source-selected target rows, not caller cache or other products.
        client.set_markets([client.parse_market(copy.deepcopy(p["raw_rows"][row["raw_index"]])) for row in p["observations"]])
        owners()
        execution = engine._execution_settings(record["stock_code"], record)
        settings = engine._observe_account(record["stock_code"], execution, reduce_only=False)
        native_account = observe_account_context(client, engine.mode)
        owners()
        if document is not None:
            contract = b["identity"]["payload"]["order_contract"]
            if (canonical_bytes(execution) != canonical_bytes(contract["execution"])
                    or canonical_bytes(settings) != canonical_bytes(contract["account_observation"])
                    or canonical_bytes(native_account) != canonical_bytes(account)):
                Prepared._fail()
        else:
            account = native_account
        client_binding = Prepare._client_binding(client)
        with database.transaction():
            finished = utc_now_ms()
            owners(owned=True)
            chan.assert_account_new_risk_allowed(account)
            current, _ = local_view()
            if (canonical_bytes(Prepare._stable_local_view(current)) != local
                    or _sha(Transition._records(chan)) != records or Transition._prefix(database) != prefix):
                Prepared._fail()
            checked = current["opening_inputs"]["checked_at_ms"]
            if type(finished) is not int or not finished <= checked < 2**63:
                Prepared._fail()
            finished = checked
            _, rows = Instrument._cache_view(engine, p["codes"], reference, ccxt, p["venue"], engine.mode)
            if canonical_bytes(rows) != canonical_bytes([{key: row[key] for key in ("market", "active", "native_state")} for row in p["observations"]]):
                Prepared._fail()
            if document is not None:
                Prepared.assert_native_prepared_intent_current(engine, record_id)
            owners(owned=True)
            if Prepare._client_binding(client) != client_binding:
                Prepared._fail()
            finished = utc_now_ms()
            owners(owned=True)
            current, _ = local_view()
            if (canonical_bytes(Prepare._stable_local_view(current)) != local or _sha(Transition._records(chan)) != records
                    or Transition._prefix(database) != prefix or type(finished) is not int
                    or not finished <= current["opening_inputs"]["checked_at_ms"] < 2**63):
                Prepared._fail()
            finished = current["opening_inputs"]["checked_at_ms"]
            owners(owned=True)
        owners()
        if (type(finished) is not int or not started <= p["started_ms"] <= p["finished_ms"] <= finished < 2**63
                or finished-p["started_ms"] > instrument_max_age_ms
                or p["finished_ms"]-p["started_ms"] > instrument_max_observation_span_ms):
            Prepared._fail()
    except Exception:
        if client is not None and engine.exchange is client:
            engine.exchange = None
        if source_started and account is not None:
            try:
                Boundary._same_database(chan, database, connection, table, owned=False)
                with database.transaction():
                    if not risk_state(database, account)["frozen"]:
                        from .NativeAccountCheck import _publish_unavailable
                        request = {"before": "0"*64, "after": "0"*64, "wallets": [], "executions": [], "pending": "0"*64, "balance": "0"*64}
                        _publish_unavailable(database, account, request)
            except Exception:
                Prepared._fail()
        Prepared._fail()
