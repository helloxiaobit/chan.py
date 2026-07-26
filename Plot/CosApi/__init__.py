"""图床上传(可选):backend 由 config.yaml cos.backend 决定(minio / txcos / none)"""
from typing import Optional

from Common.ChanException import CChanException, ErrCode


def get_cos_conf() -> dict:
    try:
        from Config.EnvConfig import CEnv
        return CEnv.get_instance().cos_conf
    except Exception:
        return {}


def upload_file(path: str, conf: Optional[dict] = None) -> str:
    """上传文件并返回可访问 url"""
    conf = conf or get_cos_conf()
    backend = conf.get("backend", "none")
    if backend == "minio":
        from .minio_api import minio_upload
        return minio_upload(path, conf.get("minio", {}))
    if backend == "txcos":
        from .txcos_api import txcos_upload
        return txcos_upload(path, conf.get("txcos", {}))
    raise CChanException(
        "未配置图床后端(config.yaml cos.backend: minio/txcos),无法上传图片",
        ErrCode.CONFIG_ERROR,
    )
