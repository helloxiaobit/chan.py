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
    """上传并返回原 URL；空显式配置不回退，失败不泄露 SDK 原文或推断远端状态。"""
    try:
        conf = get_cos_conf() if conf is None else conf
        if not isinstance(conf, dict):
            raise ValueError("invalid upload configuration")
        backend = conf.get("backend", "none")
        if not isinstance(backend, str) or backend not in {"minio", "txcos"}:
            raise ValueError("upload backend unavailable")
        options = conf.get(backend, {})
        if not isinstance(options, dict):
            raise ValueError("invalid backend configuration")
    except Exception:
        raise CChanException("图床配置无效或未启用 minio/txcos，未执行上传", ErrCode.CONFIG_ERROR) from None
    try:
        if backend == "minio":
            from .minio_api import minio_upload
            result = minio_upload(path, options)
        else:
            from .txcos_api import txcos_upload
            result = txcos_upload(path, options)
        if type(result) is not str or not result:
            raise ValueError("upload URL unavailable")
    except Exception as error:
        # 超时/缺依赖/响应或签名 URL 失败不证明远端没有对象；禁止自动重试。
        code = ErrCode.CONFIG_ERROR if isinstance(error, CChanException) and error.errcode is ErrCode.CONFIG_ERROR else ErrCode.PLOT_ERR
        raise CChanException("图床上传未确认（后端或可选依赖不可用），未自动重试", code) from None
    return result
