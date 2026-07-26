"""通用小工具"""
import time
from functools import wraps


def retry(times: int = 3, interval: float = 1.0, exceptions=(Exception,)):
    # 网络类操作重试装饰器
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_e = None
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_e = e
                    if i < times - 1:
                        time.sleep(interval)
            raise last_e
        return wrapper
    return decorator


def singleton(cls):
    instances = {}

    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return get_instance
