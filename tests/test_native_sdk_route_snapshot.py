"""Same-call route parsing only; the original SDK never performs I/O here."""
from pathlib import Path

import ccxt
import pytest

from Common.ChanException import CChanException
from Trade import NativePreparation as Prepare


SOURCE_ENTRIES = ("fapiPrivateV3GetBalance", "fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk",
    "fapiPrivateGetSymbolConfig", "fapiPrivateGetMultiAssetsMargin", "fapiPrivateGetOpenAlgoOrders",
    "fapiPublicGetPremiumIndex", "fapiPublicGetTickerBookTicker", "fapiPublicGetExchangeInfo")
ORDER_ENTRIES = ("fapiPrivatePostOrder", "fapiPrivateGetOrder", "fapiPrivateDeleteOrder",
    "fapiPrivateGetAllOrders", "fapiPrivateGetOpenOrders")


@pytest.fixture
def sdk(monkeypatch):
    calls = []
    def no_network(*args, **kwargs):
        calls.append(1)
        raise AssertionError("SDK identity verification must never use a native endpoint")
    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("socket.getaddrinfo", no_network)
    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    exchange = ccxt.binanceusdm()
    yield exchange
    assert calls == []


def route_file(exchange):
    owner = next(cls for cls in type(exchange).__mro__ if ORDER_ENTRIES[0] in vars(cls))
    return Path(ccxt.__file__).resolve().parent.joinpath(*owner.__module__.split(".")[1:]).with_suffix(".py")


def watch_route_reads(monkeypatch, path, change):
    reads = []
    def reader(original):
        def read(actual, *args, **kwargs):
            source = original(actual, *args, **kwargs)
            if actual == path:
                reads.append(actual)
                return change(source, len(reads))
            return source
        return read
    for name in ("read_text", "read_bytes"):
        monkeypatch.setattr(Path, name, reader(getattr(Path, name)))
    return reads


@pytest.mark.parametrize("entries", [(), SOURCE_ENTRIES], ids=["execution", "management-sources"])
def test_route_file_is_parsed_once_and_reread_before_return_without_cross_call_cache(sdk, monkeypatch, entries):
    path = route_file(sdk)
    source, parse = path.read_bytes(), Prepare.ast.parse
    reads = watch_route_reads(monkeypatch, path, lambda source, count: source)
    parses = []
    def parsed(actual, *args, **kwargs):
        if actual in (source, source.decode("utf-8")):
            parses.append(actual)
        return parse(actual, *args, **kwargs)
    monkeypatch.setattr(Prepare.ast, "parse", parsed)
    for invocation in (1, 2):
        assert Prepare._assert_execution_sdk(sdk, "live", source_entries=entries) is None
        assert len(reads) == 2*invocation, "fresh initial read plus final byte check, never a cross-call cache"
        assert len(parses) == invocation, "all original Entry checks must share only this call's parsed route file"


def test_route_source_byte_drift_is_rejected_before_success_without_editing_installed_sdk(sdk, monkeypatch):
    def change(source, count):
        if count > 1:
            suffix = "\n# injected same-call source drift\n"
            return source+(suffix.encode() if type(source) is bytes else suffix)
        return source
    reads = watch_route_reads(monkeypatch, route_file(sdk), change)
    with pytest.raises(CChanException):
        Prepare._assert_execution_sdk(sdk, "live", source_entries=SOURCE_ENTRIES)
    assert len(reads) == 2


@pytest.mark.parametrize("name", ORDER_ENTRIES+SOURCE_ENTRIES)
def test_shared_source_tree_does_not_skip_any_original_or_final_source_entry(sdk, monkeypatch, name):
    owner = next(cls for cls in type(sdk).__mro__ if name in vars(cls))
    entry = vars(owner)[name]
    def change(source, count):
        if count == 1:
            monkeypatch.setattr(entry, "path", entry.path+"/foreign")
        return source
    reads = watch_route_reads(monkeypatch, route_file(sdk), change)
    with pytest.raises(CChanException):
        Prepare._assert_execution_sdk(sdk, "live", source_entries=SOURCE_ENTRIES)
    assert reads
