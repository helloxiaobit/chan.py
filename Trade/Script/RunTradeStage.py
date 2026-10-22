"""Run one allowed cycle module and publish only its software notification counts."""
import os
import runpy
import sys

from Common.NotificationStatus import notification_stage_identity, observe_notifications, publish_notification_summary


def _notice(reason):
    try:
        print(f"TradeStage: {reason}", file=sys.stderr)
    except Exception:
        pass


def main():
    module = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        identity = notification_stage_identity(os.environ.get("CHANPY_CYCLE_ID"),
            os.environ.get("CHANPY_CYCLE_STAGE_ID"), module)
    except Exception:
        _notice("explicit_allowed_stage_identity_unavailable")
        return 2
    original_argv, code = sys.argv, 0
    with observe_notifications() as summary:
        try:
            sys.argv = [module, *original_argv[2:]]
            runpy.run_module(module, run_name="__main__")
        except SystemExit as error:
            code = 0 if error.code is None else error.code if type(error.code) is int and -2**31 <= error.code < 2**31 else 1
        except KeyboardInterrupt:
            code = 130
        except Exception:
            code = 1
            _notice("child_stage_failed")
        finally:
            sys.argv = original_argv
            try:
                publish_notification_summary(os.environ["CHANPY_NOTIFICATION_REPORT"], summary, **identity)
            except Exception:
                _notice("notification_summary_unavailable")
    return code  # 通知/观测失败不能重写原阶段结果或订单账本。


if __name__ == "__main__":
    sys.exit(main())
