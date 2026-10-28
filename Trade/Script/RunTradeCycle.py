"""显式配置的串行运行壳；阶段完成不是策略/账户/交易所准入证明。"""
import argparse
import hashlib
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from Common.NotificationStatus import notification_report_path, read_notification_summary
from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from .OpeningInputs import COpeningInputs, inspect_opening_inputs, read_cycle_scope


ROOT = Path(__file__).resolve().parents[2]
MANAGEMENT = ("Trade.Script.CheckOpenScore", "Trade.Script.ClosePreErrorOpen",
              "Trade.Script.RealTimeTracker", "Trade.Script.RetradeCoverOrder")


def _fail():
    raise CChanException("运行配置/报告/单实例锁不可用，未获得新增风险权限", ErrCode.ENV_CONF_ERR) from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _run_lock(database):
    """锁属于实际交易库，不属于报告目录；OS 句柄退出即释放。"""
    handle, locked = None, False
    try:
        handle = database.with_name(database.name+".cycle.lock").open("a+b")
        if not handle.seek(0, os.SEEK_END):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    except OSError:
        _fail()
    finally:
        if handle is not None:
            try:
                if locked:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()


def _command(module, args, *, cwd, env):
    # 不把子进程任意日志/异常中的凭据回显或写入运行报告。
    return subprocess.run([sys.executable, "-m", "Trade.Script.RunTradeStage", module, *args], cwd=cwd, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=300).returncode


def run_trade_cycle(config_path, *, report_path, command=None, now_ms=None):
    """失败阻断新增风险；不依赖失败的行情/模型继续尝试原账户管理。"""
    command, now_ms = command or _command, now_ms or utc_now_ms
    config_path, report_path = Path(config_path).resolve(), Path(report_path).resolve()
    try:
        raw = config_path.read_bytes()
        env = CEnv(str(config_path))
        database = env.db_conf
        if database.get("type") != "sqlite" or not isinstance(database.get("sqlite_path"), str) or not database["sqlite_path"] or database["sqlite_path"] == ":memory:":
            _fail()
        database = Path(env.abs_path(database["sqlite_path"])).resolve()
        if report_path == database:
            _fail()
        fingerprint = _sha(raw)
        if _sha(config_path.read_bytes()) != fingerprint:
            _fail()
        with _run_lock(database), report_path.open("xb") as journal:
            run_id = uuid.uuid4().hex
            child_env = {**os.environ, "CHANPY_CONFIG": str(config_path), "CHANPY_CYCLE_ID": run_id}
            result = {"schema": "chan-trade-cycle-v1", "run_id": run_id, "config_sha256": fingerprint,
                "status": "completed", "exit_code": 0, "failed_stage": None, "reason": None,
                "scope": None, "quality": [], "stages": [], "notifications": [], "native_admission_verified": False}
            journal_failed = False

            def emit(event, **fields):
                nonlocal journal_failed
                if not journal_failed:
                    try:
                        journal.write(canonical_bytes({"schema": "chan-trade-cycle-event-v1", "run_id": run_id,
                            "event": event, "at_ms": now_ms(), **fields})+b"\n")
                        journal.flush()
                        os.fsync(journal.fileno())
                    except OSError:
                        journal_failed = True
                        failure("journal", "report_io_failed")

            def failure(stage, reason, code=1):
                if result["exit_code"] == 0:
                    result.update(status="failed", exit_code=code, failed_stage=stage, reason=reason)

            def unchanged():
                try:
                    return _sha(config_path.read_bytes()) == fingerprint
                except OSError:
                    return False

            def step(name, module, args=()):
                if not unchanged():
                    failure(name, "configuration_changed")
                    return False
                management = name == "restore" or name.startswith("manage:")
                if journal_failed and not management:
                    return False
                emit("stage_started", stage=name, module=module)
                if journal_failed and not management:
                    return False
                stage_id = uuid.uuid4().hex
                with notification_report_path() as observation_path:
                    stage_env = {**child_env, "CHANPY_CYCLE_STAGE_ID": stage_id}
                    stage_env.pop("CHANPY_NOTIFICATION_REPORT", None)
                    if observation_path is not None:
                        stage_env["CHANPY_NOTIFICATION_REPORT"] = str(observation_path)
                    try:
                        code = command(module, list(args), cwd=ROOT, env=stage_env)
                        if type(code) is not int or not -2**31 <= code < 2**31:
                            raise ValueError("missing child exit code")
                        reason = "child_failed" if code else None
                    except subprocess.TimeoutExpired:
                        code, reason = 1, "child_timeout"
                    except Exception:
                        code, reason = 1, "child_exception"
                    observation = read_notification_summary(observation_path, run_id=run_id, stage_id=stage_id, module=module)
                notification = {"stage": name, "observation": observation}
                result["notifications"].append(notification)
                emit("notifications", **notification)
                stage = {"name": name, "module": module, "exit_code": code, "reason": reason}
                result["stages"].append(stage)
                emit("stage_finished", stage=stage)
                if not unchanged():
                    failure(name, "configuration_changed")
                    return False
                if code:
                    failure(name, reason, code)
                return code == 0 and not journal_failed

            emit("started", config_sha256=fingerprint)
            try:
                if step("restore", "Trade.Script.RestoreOrders"):
                    try:
                        scope = result["scope"] = read_cycle_scope(env)
                    except Exception:
                        failure("scope", "scope_or_model_unavailable")
                    if result["exit_code"] == 0:
                        for code in scope["code_list"]:
                            if not step("update:"+code, "OfflineData.ccxt_update", [code, *scope["lv_list"]]):
                                break
                    if result["exit_code"] == 0:
                        try:
                            observed = inspect_opening_inputs(env, now_ms=now_ms())
                            if observed["scope"] != scope:
                                _fail()
                            result["quality"] = observed["quality"]
                            expected = {"config_sha256": fingerprint,
                                **{key: observed[key] for key in ("scope_sha256", "inputs_sha256")}}
                            child_env.update({"CHANPY_CYCLE_"+key.upper(): value for key, value in expected.items()})
                            emit("quality", observations=result["quality"])
                        except Exception:
                            failure("quality", "quality_unavailable_or_not_ready")
                    if result["exit_code"] == 0 and step("signal", "Trade.Script.SignalMonitor"):
                        try:
                            COpeningInputs(config_path, expected=expected, now_ms=now_ms)
                            result["opening_inputs"] = expected
                            emit("pre_open_inputs", inputs=expected)
                        except Exception:
                            failure("pre_open_inputs", "opening_inputs_changed_or_unavailable")
                        if result["exit_code"] == 0:
                            profile = env.get_section("trade").get("native_admission")
                            # Routing only: the original child/Engine still
                            # validates full profile, sources and monetary CAS.
                            native_route = (env.ccxt_conf.get("mode") in {"testnet", "live"}
                                and env.ccxt_conf.get("exchange") in {"binance", "binanceusdm"}
                                and env.ccxt_conf.get("default_type") == "swap"
                                and type(profile) is dict and profile.get("schema") == "chan-native-entry-profile-v1")
                            if env.ccxt_conf.get("mode") != "dry_run" and not native_route:
                                failure("account_admission", "native_fresh_admission_not_integrated")
                            else:
                                step("open", "Trade.Script.MakeOpenTrade")
            finally:
                for module in MANAGEMENT:
                    step("manage:"+module.rsplit(".", 1)[-1], module)
            emit("finished", result=result)
            return result
    except Exception:
        _fail()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    try:
        result = run_trade_cycle(args.config, report_path=args.report)
        print(f"TradeCycle {result['run_id']}: {result['status']} ({result['reason'] or 'completed'})")
        return 0 if result["status"] == "completed" else max(1, result["exit_code"])
    except CChanException:
        print("TradeCycle: explicit configuration/report/lock unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
