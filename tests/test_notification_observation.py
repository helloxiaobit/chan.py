"""Real notification dispatch with fake transport only; no actual credentials/I/O."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from Common import send_msg_cmd as notify
from .test_execution_store import store
from .test_linear_paper_engine import paper_engine
from .test_linear_paper_account import CODE
from .test_m6_trade import make_signal


SECRET = "SYNTHETIC_PRIVATE_TOKEN_NOT_FOR_LOGS"


@pytest.fixture()
def configure(tmp_path, monkeypatch):
    path = tmp_path/"runtime.json"
    monkeypatch.setenv("CHANPY_CONFIG", str(path))

    def setup(backend):
        options = {"bot_token": SECRET, "chat_id": "synthetic-chat", "webhook": "https://invalid.test/"+SECRET,
            "url": "https://invalid.test", "token": SECRET, "smtp_host": "invalid.test", "user": "synthetic@invalid.test",
            "password": SECRET, "to": "recipient@invalid.test"}
        path.write_bytes(canonical_bytes({"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
            "ccxt": {"mode": "dry_run", "exchange": "binance"}, "notify": {"backend": backend, backend: options}}))
        CEnv.reset_instance()
        return options

    yield setup
    CEnv.reset_instance()


def http_response(payload, *, ok=True):
    return SimpleNamespace(ok=ok, status_code=200 if ok else 503, json=lambda: payload)


@pytest.mark.parametrize("backend", ["telegram", "dingtalk", "wecom", "gotify"])
def test_transport_exceptions_never_print_private_text(configure, monkeypatch, capsys, backend):
    import requests
    configure(backend)
    def fail(*args, **kwargs):
        raise requests.ConnectionError("https://invalid.test/?token="+SECRET)
    monkeypatch.setattr(requests, "post", fail)
    assert notify.send_msg("synthetic title", "synthetic body") is False
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err and "Traceback" not in captured.out+captured.err
    assert "delivery_failed" in captured.out+captured.err


@pytest.mark.parametrize("backend", ["telegram", "dingtalk", "wecom", "gotify"])
def test_http_failure_is_observable_without_logging_response_body(configure, monkeypatch, capsys, backend):
    import requests
    configure(backend)
    monkeypatch.setattr(requests, "post", lambda *a, **k: http_response({"error": SECRET}, ok=False))
    assert notify.send_msg("synthetic title", "synthetic body") is False
    captured = capsys.readouterr()
    assert "delivery_failed" in captured.out+captured.err and SECRET not in captured.out+captured.err


@pytest.mark.parametrize("backend,body", [("telegram", {"ok": False, "description": SECRET}),
    ("dingtalk", {"errcode": 310000, "errmsg": SECRET}), ("wecom", {"errcode": 40014, "errmsg": SECRET}),
    ("gotify", {"error": SECRET}), ("telegram", {"ok": "true"}), ("wecom", {"errcode": False})])
def test_http_200_is_not_success_without_the_backend_ack(configure, monkeypatch, backend, body):
    import requests
    configure(backend)
    monkeypatch.setattr(requests, "post", lambda *a, **k: http_response(body))
    assert notify.send_msg("synthetic title", "synthetic body") is False


@pytest.mark.parametrize("backend,body", [("telegram", {"ok": True, "result": {"message_id": 1}}),
    ("dingtalk", {"errcode": 0, "errmsg": "ok"}), ("wecom", {"errcode": 0, "errmsg": "ok"}), ("gotify", {"id": 1})])
def test_explicit_backend_ack_preserves_the_existing_boolean_interface(configure, monkeypatch, backend, body):
    import requests
    configure(backend)
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return http_response(body)
    monkeypatch.setattr(requests, "post", post)
    assert notify.send_msg("synthetic title", "synthetic body") is True
    assert len(calls) == 1 and calls[0]["timeout"] == 30


def test_unknown_backend_cannot_fall_back_to_none_or_print_the_message(configure, capsys):
    configure("unknown-"+SECRET)
    assert notify.send_msg("synthetic title", "BODY_MUST_NOT_APPEAR") is False
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err and "BODY_MUST_NOT_APPEAR" not in captured.out+captured.err


def test_smtp_partial_rejection_is_false_and_connection_timeout_is_bounded(configure, monkeypatch, capsys):
    import smtplib
    configure("email")
    calls = []
    class SMTP:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, *args):
            return 235, b"ok"
        def send_message(self, message):
            return {"recipient@invalid.test": (550, SECRET.encode())}
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    assert notify.send_msg("synthetic title", "synthetic body") is False
    assert calls == [{"timeout": 30}]
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err


def test_summary_is_scoped_nested_and_never_keeps_message_or_credentials(configure, monkeypatch):
    from Common.NotificationStatus import observe_notifications
    import requests
    configure("none")
    with observe_notifications() as original:
        assert notify.send_msg("synthetic title", "synthetic body") is True
        with observe_notifications() as nested:
            configure("telegram")
            monkeypatch.setattr(requests, "post", lambda *a, **k: http_response({"ok": False, "description": SECRET}))
            assert notify.send_msg(SECRET, SECRET) is False
        assert nested.snapshot() == [{"backend": "telegram", "attempted": 1, "accepted": 0, "failed": 1, "local_only": 0}]
        configure("none")
        assert notify.send_msg("synthetic title", "synthetic body") is True
    assert original.snapshot() == [{"backend": "none", "attempted": 2, "accepted": 0, "failed": 0, "local_only": 2}]
    snapshot = original.snapshot()
    snapshot[0]["failed"] = 999
    assert original.snapshot()[0]["failed"] == 0
    assert SECRET not in json.dumps(nested.snapshot()) and original.complete and nested.complete


def test_interrupted_transport_cannot_be_reported_as_zero_failed_complete_observation(configure, monkeypatch):
    from Common.NotificationStatus import observe_notifications
    import requests
    configure("telegram")
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(requests, "post", interrupted)
    with observe_notifications() as summary:
        with pytest.raises(KeyboardInterrupt):
            notify.send_msg("synthetic title", "synthetic body")
    assert summary.snapshot()[0]["attempted"] == 1 and not summary.complete


def test_configuration_load_failure_is_not_a_successful_none_notification(configure, capsys):
    configure("telegram")
    Path(os.environ["CHANPY_CONFIG"]).write_text("notify: ["+SECRET, encoding="utf-8")
    CEnv.reset_instance()
    assert notify.send_msg("synthetic title", "BODY_MUST_NOT_APPEAR") is False
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err and "BODY_MUST_NOT_APPEAR" not in captured.out+captured.err


@pytest.mark.parametrize("section", [[SECRET], None, SECRET])
def test_explicit_invalid_notify_section_cannot_silently_disable_notifications(configure, capsys, section):
    configure("telegram")
    Path(os.environ["CHANPY_CONFIG"]).write_bytes(canonical_bytes({"notify": section}))
    CEnv.reset_instance()
    assert notify.send_msg("synthetic title", "BODY_MUST_NOT_APPEAR") is False
    captured = capsys.readouterr()
    assert SECRET not in captured.out+captured.err and "BODY_MUST_NOT_APPEAR" not in captured.out+captured.err


def test_notification_failure_cannot_undo_or_repeat_the_actual_paper_fill(configure, monkeypatch, store):
    from Common.NotificationStatus import observe_notifications
    import requests
    configure("telegram")
    def fail(*args, **kwargs):
        raise requests.ConnectionError(SECRET)
    monkeypatch.setattr(requests, "post", fail)
    db, _ = store
    trade = paper_engine(db)
    trade.push_msg = True
    trade.set_sim_quote(CODE, at_ms=1001, bid="99.9", ask="100", mark_price="100")
    record = db.get_record(db.add_signal(make_signal(code=CODE)))
    with observe_notifications() as summary:
        result = trade.add_trade(record, 102)
    assert result.filled == db.get_record(record["id"])["current_qty"] == 0.03
    assert len(trade.sim_state.orders) == 1 and trade.get_sim_account_report()["account"]["events"]
    assert summary.snapshot() == [{"backend": "telegram", "attempted": 1, "accepted": 0, "failed": 1, "local_only": 0}]
