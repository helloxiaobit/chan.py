"""带异常捕获的线程封装(例行脚本并发跑多票用)"""
import threading
import traceback


class CCommonThread(threading.Thread):
    def __init__(self, target, args=(), kwargs=None, name=None):
        super().__init__(name=name, daemon=True)
        self._target_func = target
        self._args = args
        self._kwargs = kwargs or {}
        self.result = None
        self.exception = None

    def run(self):
        try:
            self.result = self._target_func(*self._args, **self._kwargs)
        except Exception as e:
            self.exception = e
            print(f"[CCommonThread:{self.name}] 异常:\n{traceback.format_exc()}")

    def join_with_result(self, timeout=None):
        self.join(timeout)
        if self.exception is not None:
            raise self.exception
        return self.result
