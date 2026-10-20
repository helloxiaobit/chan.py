"""参数/评估产物的有限字节与原子 write-once 发布，不修改活动配置。"""
import os
from pathlib import Path
import tempfile

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes


def write_once(path, raw):
    destination = Path(path).resolve()
    if type(raw) is not bytes or destination.exists() or not destination.parent.is_dir():
        raise CChanException("产物目标存在、父目录缺失或字节类型无效", ErrCode.CONFIG_ERROR)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except OSError as error:
        raise CChanException("write-once 发布失败", ErrCode.CONFIG_ERROR) from error
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return str(destination)


def write_json_once(path, payload):
    return write_once(path, canonical_bytes(payload))
