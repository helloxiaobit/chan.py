"""真实配置/SQLite 质量与操作流水线；只有子进程传输是 fake。"""
import json
from pathlib import Path

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from OfflineData.offline_data_util import CKLineDB
from Trade.Script.RunTradeCycle import run_trade_cycle


ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
NOW = 24 * HOUR
CODES = ["ALPHA/USDT:USDT", "BETA/USDT:USDT"]
SOURCE = dict(exchange="binance", market_type="swap", settle="USDT", price_type="contract")
MANAGEMENT = ["Trade.Script.CheckOpenScore", "Trade.Script.ClosePreErrorOpen",
              "Trade.Script.RealTimeTracker", "Trade.Script.RetradeCoverOrder"]


@pytest.fixture()
def cycle(tmp_path):
    import yaml
    market = tmp_path / "market.db"
    with CKLineDB(str(market)) as db:
        db.bind_source(SOURCE)
        for code in CODES:
            for level, interval in ((KL_TYPE.K_4H, 4*HOUR), (KL_TYPE.K_60M, HOUR)):
                db.upsert_klines(code, level, [(ts, 100, 101, 99, 100, 1) for ts in range(0, NOW, interval)])
    conf = {"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
        "offline_data": {"sqlite_path": str(market), "source_identity": SOURCE},
        "ccxt": {"mode": "dry_run", "exchange": "binance", "default_type": "swap"},
        "trade": {"code_list": CODES, "lv_list": ["K_4H", "K_60M"], "strategy": "multi_lv"},
        "notify": {"backend": "none"}}
    path = tmp_path/"cycle config.yaml"
    path.write_text(yaml.safe_dump(conf), encoding="utf-8")
    return path, tmp_path/"report.jsonl", conf


def command_log(*, fail=None, mutate=None):
    calls = []
    def command(module, args, *, cwd, env):
        calls.append((module, args, cwd, env.copy()))
        if mutate:
            mutate(module)
        return 37 if module == fail else 0
    return calls, command


def run(cycle, command):
    return run_trade_cycle(cycle[0], report_path=cycle[1], command=command, now_ms=lambda: NOW)


def test_configured_symbols_levels_and_one_environment_drive_the_whole_run(cycle):
    calls, command = command_log()
    result = run(cycle, command)
    modules = [row[0] for row in calls]
    assert modules == ["Trade.Script.RestoreOrders", "OfflineData.ccxt_update", "OfflineData.ccxt_update",
                       "Trade.Script.SignalMonitor", "Trade.Script.MakeOpenTrade", *MANAGEMENT]
    updates = [row[1] for row in calls if row[0] == "OfflineData.ccxt_update"]
    assert updates == [[code, "K_4H", "K_60M"] for code in CODES]
    assert all(row[2] == ROOT and row[3]["CHANPY_CONFIG"] == str(cycle[0].resolve()) for row in calls)
    assert all(row[3]["CHANPY_CYCLE_ID"] == result["run_id"] for row in calls)
    assert result["status"] == "completed" and result["exit_code"] == 0
    assert len(result["quality"]) == 4
    assert all(row["ready"] and row["latest_close_ms"] == NOW for row in result["quality"])
    events = [json.loads(raw) for raw in cycle[1].read_text().splitlines()]
    assert events[0]["event"] == "started" and events[-1]["event"] == "finished"
    assert events[-1]["result"] == result
    assert "BTC" not in cycle[1].read_text() and "ETH" not in cycle[1].read_text()


@pytest.mark.parametrize("failed", ["Trade.Script.RestoreOrders", "OfflineData.ccxt_update", "Trade.Script.SignalMonitor"])
def test_failed_input_never_opens_new_risk_but_all_management_is_attempted(cycle, failed):
    calls, command = command_log(fail=failed)
    result = run(cycle, command)
    modules = [row[0] for row in calls]
    assert "Trade.Script.MakeOpenTrade" not in modules
    assert modules[-4:] == MANAGEMENT
    assert result["status"] == "failed" and result["exit_code"] == 37
    assert result["failed_stage"] is not None


@pytest.mark.parametrize("damage", ["stale", "gap", "source"])
def test_quality_is_actually_read_from_the_configured_sqlite_before_signal_or_open(cycle, damage):
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        if damage == "source":
            db.conn.execute("UPDATE kline_source SET payload=?", (json.dumps({**SOURCE, "exchange": "okx"}),))
        else:
            at = NOW-HOUR if damage == "stale" else 2*HOUR
            db.conn.execute("DELETE FROM kline WHERE symbol=? AND lv=? AND ts=?", (CODES[0], "K_60M", at))
        db.conn.commit()
    calls, command = command_log()
    result = run(cycle, command)
    modules = [row[0] for row in calls]
    assert "Trade.Script.SignalMonitor" not in modules and "Trade.Script.MakeOpenTrade" not in modules
    assert modules[-4:] == MANAGEMENT and result["status"] == "failed"
    assert result["failed_stage"] == "quality"


def test_management_failures_do_not_skip_later_management(cycle):
    calls, command = command_log(fail=MANAGEMENT[0])
    result = run(cycle, command)
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["status"] == "failed" and result["exit_code"] == 37


def test_existing_report_is_refused_before_any_child_without_overwriting(cycle):
    cycle[1].write_bytes(b"original")
    calls, command = command_log()
    with pytest.raises(CChanException):
        run(cycle, command)
    assert calls == [] and cycle[1].read_bytes() == b"original"


def test_child_exceptions_are_redacted_and_new_risk_stops(cycle):
    calls = []
    def command(module, args, **kwargs):
        calls.append(module)
        if module == "OfflineData.ccxt_update":
            raise RuntimeError("api_key=VERY_PRIVATE secret=DO_NOT_LOG")
        return 0
    result = run(cycle, command)
    assert "Trade.Script.MakeOpenTrade" not in calls and calls[-4:] == MANAGEMENT
    assert "VERY_PRIVATE" not in cycle[1].read_text() and "DO_NOT_LOG" not in str(result)
    assert result["status"] == "failed"


def test_configuration_drift_is_not_given_to_a_later_order_or_account_manager(cycle):
    def mutate(module):
        if module == "OfflineData.ccxt_update":
            cycle[0].write_text("ccxt: {mode: live}\n", encoding="utf-8")
    calls, command = command_log(mutate=mutate)
    result = run(cycle, command)
    assert [row[0] for row in calls] == ["Trade.Script.RestoreOrders", "OfflineData.ccxt_update"]
    assert result["status"] == "failed" and result["reason"] == "configuration_changed"


def test_non_dry_new_risk_is_closed_until_fresh_native_admission_is_integrated(cycle):
    import yaml
    cycle[2]["ccxt"]["mode"] = "testnet"
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    calls, command = command_log()
    result = run(cycle, command)
    assert "Trade.Script.MakeOpenTrade" not in [row[0] for row in calls]
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["reason"] == "native_fresh_admission_not_integrated"


def test_single_instance_lock_is_scoped_to_trade_db_not_report_filename(cycle):
    nested_calls = []
    def command(module, args, **kwargs):
        if module == "OfflineData.ccxt_update":
            with pytest.raises(CChanException):
                run_trade_cycle(cycle[0], report_path=cycle[1].with_name("other.jsonl"),
                    command=lambda *a, **k: nested_calls.append(a), now_ms=lambda: NOW)
        return 0
    result = run(cycle, command)
    assert nested_calls == [] and result["status"] == "completed"
    # The OS lock is released after terminal completion, not a stale marker file.
    result = run_trade_cycle(cycle[0], report_path=cycle[1].with_name("later.jsonl"), command=command_log()[1], now_ms=lambda: NOW)
    assert result["status"] == "completed"


def test_successful_cli_returns_zero_from_the_actual_cycle(cycle, monkeypatch):
    from Trade.Script import RunTradeCycle as module
    monkeypatch.setattr(module, "_command", command_log()[1])
    monkeypatch.setattr(module, "utc_now_ms", lambda: NOW)
    monkeypatch.setattr("sys.argv", ["TradeCycle", "--config", str(cycle[0]), "--report", str(cycle[1])])
    assert module.main() == 0


def test_signal_monitor_cli_propagates_real_offline_input_failure(cycle):
    import os
    import subprocess
    import sys
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        db.conn.execute("DELETE FROM kline_source")
        db.conn.commit()
    result = subprocess.run([sys.executable, "-m", "Trade.Script.SignalMonitor"], cwd=ROOT,
        env={**os.environ, "CHANPY_CONFIG": str(cycle[0])}, capture_output=True, text=True, timeout=30)
    assert "计算失败" in result.stdout
    assert result.returncode != 0


@pytest.mark.parametrize("kind", ["powershell", "bash"])
def test_update_wrappers_run_one_checked_configured_cycle_not_a_duplicate_order_chain(tmp_path, kind):
    import os
    import shutil
    import subprocess
    fake, log, argv = tmp_path/"fake", tmp_path/"calls.log", tmp_path/"argv.log"
    fake.mkdir()
    config, report = tmp_path/"explicit config.yaml", tmp_path/"explicit report.jsonl"
    config.write_text("{}")
    script = ROOT/"Trade"/"Script"/("update_data_signal.ps1" if kind == "powershell" else "update_data_signal.sh")
    if kind == "powershell":
        host = shutil.which("pwsh")
        if not host:
            pytest.skip("PowerShell unavailable; no wrapper claim")
        (fake/"python.cmd").write_bytes((f'@echo off\r\necho invoked>>"{log}"\r\necho %*>>"{argv}"\r\nexit /b 37\r\n').encode())
        command = [host, "-NoProfile", "-NonInteractive", "-File", str(script), str(config), str(report)]
    else:
        host = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else Path(shutil.which("bash") or "missing")
        if not host.is_file():
            pytest.skip("Bash unavailable; no wrapper claim")
        (fake/"python").write_bytes((f'#!/bin/bash\necho invoked >> "{log.as_posix()}"\nprintf "%s\\n" "$@" >> "{argv.as_posix()}"\nexit 37\n').encode())
        (fake/"python").chmod(0o755)
        command = [str(host), str(script), str(config), str(report)]
    result = subprocess.run(command, cwd=tmp_path, env={**os.environ, "PATH": str(fake)+os.pathsep+os.environ["PATH"]},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 37, result.stderr
    assert len(log.read_text().splitlines()) == 1
    assert "Trade.Script.RunTradeCycle" in argv.read_text()
    assert "--config" in argv.read_text() and "--report" in argv.read_text()


def test_report_io_failure_blocks_new_risk_but_does_not_stop_existing_management(cycle, monkeypatch):
    from Trade.Script import RunTradeCycle as module
    def disk_failed(*args):
        raise OSError("private disk diagnostic must not escape")
    monkeypatch.setattr(module.os, "fsync", disk_failed)
    calls, command = command_log()
    result = run(cycle, command)
    assert "Trade.Script.MakeOpenTrade" not in [row[0] for row in calls]
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["reason"] == "report_io_failed" and result["status"] == "failed"


def test_report_failure_at_open_boundary_is_not_ignored_after_successful_inputs(cycle, monkeypatch):
    from Trade.Script import RunTradeCycle as module
    real_fsync = module.os.fsync
    def disk_failed_at_open(fd):
        if b'"stage":"open"' in cycle[1].read_bytes():
            raise OSError("disk stopped at the order boundary")
        real_fsync(fd)
    monkeypatch.setattr(module.os, "fsync", disk_failed_at_open)
    calls, command = command_log()
    result = run(cycle, command)
    assert "Trade.Script.MakeOpenTrade" not in [row[0] for row in calls]
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["reason"] == "report_io_failed"


def test_default_transport_has_a_bounded_timeout_and_does_not_capture_private_output(cycle, monkeypatch):
    import subprocess
    from Trade.Script import RunTradeCycle as module
    calls = []
    def transport(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["timeout"] == 300
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired(argv, 300, output="secret token should not be logged")
    monkeypatch.setattr(module.subprocess, "run", transport)
    result = run_trade_cycle(cycle[0], report_path=cycle[1], now_ms=lambda: NOW)
    assert len(calls) == 5  # restore and each separate management attempt
    assert result["reason"] == "child_timeout" and "secret token" not in cycle[1].read_text()


def test_notification_failure_is_recorded_without_failing_successful_stages(cycle, monkeypatch):
    from Common.NotificationStatus import observe_notifications, publish_notification_summary
    from Common.send_msg_cmd import send_msg
    from Config.EnvConfig import CEnv
    import yaml
    cycle[2]["notify"] = {"backend": "telegram", "telegram": {}}  # missing dummy credentials; never calls transport
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    monkeypatch.setenv("CHANPY_CONFIG", str(cycle[0]))
    CEnv.reset_instance()
    def command(module, args, *, env, **kwargs):
        with observe_notifications() as summary:
            assert send_msg("synthetic title", "synthetic body") is False
        publish_notification_summary(env["CHANPY_NOTIFICATION_REPORT"], summary, run_id=env["CHANPY_CYCLE_ID"],
            stage_id=env["CHANPY_CYCLE_STAGE_ID"], module=module)
        return 0
    try:
        result = run(cycle, command)
        assert result["status"] == "completed" and all(row["exit_code"] == 0 for row in result["stages"])
        assert len(result["notifications"]) == len(result["stages"])
        assert all(row["observation"]["state"] == "complete" and row["observation"]["counts"][0]["failed"] == 1 for row in result["notifications"])
        assert '"event":"notifications"' in cycle[1].read_text()
    finally:
        CEnv.reset_instance()


def test_missing_notification_summary_is_unknown_not_a_fabricated_clean_count(cycle):
    result = run(cycle, command_log()[1])
    assert result["status"] == "completed"
    assert result["notifications"] and all(row["observation"] == {"state": "unavailable", "counts": None} for row in result["notifications"])


@pytest.mark.parametrize("failure", ["storage", "malformed", "cleanup"])
def test_observation_failure_cannot_skip_successful_stages_or_echo_its_bytes(cycle, monkeypatch, failure):
    from Common import NotificationStatus as status
    secret = "SYNTHETIC_OBSERVATION_SECRET"
    if failure == "storage":
        def unavailable(*args, **kwargs):
            raise OSError(secret)
        monkeypatch.setattr(status, "TemporaryDirectory", unavailable)
    elif failure == "cleanup":
        class UnavailableCleanup:
            name = str(cycle[1].parent)
            def cleanup(self):
                raise OSError(secret)
        monkeypatch.setattr(status, "TemporaryDirectory", lambda *a, **k: UnavailableCleanup())
    calls = []
    def command(module, args, *, env, **kwargs):
        calls.append(module)
        if failure == "malformed":
            Path(env["CHANPY_NOTIFICATION_REPORT"]).write_bytes(secret.encode())
        elif failure == "storage":
            assert "CHANPY_NOTIFICATION_REPORT" not in env
        return 0
    result = run(cycle, command)
    assert result["status"] == "completed" and calls[-4:] == MANAGEMENT
    assert all(row["observation"] == {"state": "unavailable", "counts": None} for row in result["notifications"])
    assert secret not in cycle[1].read_text()


def test_malformed_config_never_leaks_yaml_lines_or_starts_a_child(cycle, monkeypatch, capsys):
    from Trade.Script import RunTradeCycle as module
    cycle[0].write_text("secret: [DO_NOT_PRINT_SECRET\ncredentials: !bad\n", encoding="utf-8")
    calls, command = command_log()
    monkeypatch.setattr(module, "_command", command)
    monkeypatch.setattr("sys.argv", ["TradeCycle", "--config", str(cycle[0]), "--report", str(cycle[1])])
    assert module.main() == 2
    output = capsys.readouterr()
    assert "DO_NOT_PRINT_SECRET" not in output.out+output.err and calls == []


def test_another_process_cannot_bypass_the_actual_os_lock_with_another_report(cycle):
    import os
    import subprocess
    import sys
    observations = []
    def command(module, args, **kwargs):
        if module == "OfflineData.ccxt_update" and not observations:
            contender = subprocess.run([sys.executable, "-m", "Trade.Script.RunTradeCycle", "--config", str(cycle[0]),
                "--report", str(cycle[1].with_name("contender.jsonl"))], cwd=ROOT,
                env={**os.environ, "CHANPY_CONFIG": str(cycle[0])}, capture_output=True, text=True, timeout=30)
            observations.append(contender.returncode)
        return 0
    assert run(cycle, command)["status"] == "completed"
    assert observations == [2] and not cycle[1].with_name("contender.jsonl").exists()


@pytest.mark.parametrize("bad", ["symbols", "levels", "model"])
def test_no_demo_scope_or_silent_model_fallback_when_inputs_are_incomplete(cycle, bad):
    import yaml
    if bad == "symbols":
        cycle[2]["trade"].pop("code_list")
    elif bad == "levels":
        cycle[2]["trade"]["lv_list"] = ["K_60M", "K_4H"]
    else:
        cycle[2]["model"] = {"required": True}
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    calls, command = command_log()
    result = run(cycle, command)
    assert [row[0] for row in calls] == ["Trade.Script.RestoreOrders", *MANAGEMENT]
    assert result["reason"] == "scope_or_model_unavailable"


def test_quality_observer_does_not_create_tables_in_an_unrelated_sqlite_file(cycle):
    import sqlite3
    market = Path(cycle[2]["offline_data"]["sqlite_path"])
    market.unlink()  # owned synthetic fixture only
    with sqlite3.connect(market) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.execute("INSERT INTO unrelated VALUES('preserve')")
    original = market.read_bytes()
    calls, command = command_log()
    result = run(cycle, command)
    assert result["failed_stage"] == "quality"
    assert market.read_bytes() == original
    assert "Trade.Script.MakeOpenTrade" not in [row[0] for row in calls]


def test_shared_quality_reader_can_be_explicitly_read_only_without_changing_writer_defaults(tmp_path):
    import sqlite3
    path = tmp_path/"readonly.db"
    with CKLineDB(str(path)) as writer:
        writer.bind_source(SOURCE)
        writer.upsert_klines(CODES[0], KL_TYPE.K_60M, [(0, 100, 101, 99, 100, 1)])
    with CKLineDB(str(path), read_only=True) as reader:
        assert reader.inspect_quality(CODES[0], KL_TYPE.K_60M, now_ms=HOUR)["ready"]
        with pytest.raises(sqlite3.OperationalError):
            reader.conn.execute("DELETE FROM kline")
    missing = tmp_path/"must-not-create.db"
    with pytest.raises(sqlite3.OperationalError):
        CKLineDB(str(missing), read_only=True)
    assert not missing.exists()


def test_report_cannot_create_a_json_journal_at_the_not_yet_created_trade_db(cycle):
    database = Path(cycle[2]["db"]["sqlite_path"])
    calls, command = command_log()
    with pytest.raises(CChanException):
        run_trade_cycle(cycle[0], report_path=database, command=command, now_ms=lambda: NOW)
    assert not database.exists() and calls == []


def test_powershell_resolves_relative_report_against_powershell_location_not_process_cwd(tmp_path):
    import os
    import shutil
    import subprocess
    host = shutil.which("pwsh")
    if not host:
        pytest.skip("PowerShell unavailable; no relative-path claim")
    fake = tmp_path/"fake"
    fake.mkdir()
    argv = tmp_path/"args.log"
    (fake/"python.cmd").write_bytes((f'@echo off\r\necho %*>>"{argv}"\r\nexit /b 37\r\n').encode())
    (tmp_path/"config.yaml").write_text("{}")
    script = ROOT/"Trade"/"Script"/"update_data_signal.ps1"
    # Set-Location is different from the process cwd used by System.IO.Path.
    literal = lambda path: "'"+str(path).replace("'", "''")+"'"
    expression = f"Set-Location -LiteralPath {literal(tmp_path)}; & {literal(script)} config.yaml report.jsonl; exit $LASTEXITCODE"
    result = subprocess.run([host, "-NoProfile", "-NonInteractive", "-Command", expression], cwd=ROOT,
        env={**os.environ, "PATH": str(fake)+os.pathsep+os.environ["PATH"]}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 37, result.stderr
    assert str(tmp_path/"report.jsonl") in argv.read_text()


@pytest.mark.parametrize("damage", ["gap", "source", "clock", "revision"])
def test_successful_signal_process_cannot_outlive_its_actual_input_epoch(cycle, damage):
    clock = {"now": NOW}
    def mutate(module):
        if module == "Trade.Script.SignalMonitor":
            if damage == "clock":
                clock["now"] += HOUR
            else:
                with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
                    if damage == "gap":
                        market.conn.execute("DELETE FROM kline WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], HOUR))
                    elif damage == "revision":
                        market.conn.execute("UPDATE kline SET v=9 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], HOUR))
                    else:
                        market.conn.execute("UPDATE kline_source SET payload=?", (json.dumps({**SOURCE, "exchange": "okx"}),))
                    market.conn.commit()
    calls, command = command_log(mutate=mutate)
    result = run_trade_cycle(cycle[0], report_path=cycle[1], command=command, now_ms=lambda: clock["now"])
    assert "Trade.Script.MakeOpenTrade" not in [row[0] for row in calls]
    assert [row[0] for row in calls][-4:] == MANAGEMENT
    assert result["failed_stage"] == "pre_open_inputs"
