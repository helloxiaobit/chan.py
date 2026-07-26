"""minio 图床后端(可选依赖 pip install minio)

config.yaml 配置示例:
cos:
  backend: minio
  minio:
    endpoint: 127.0.0.1:9000
    access_key: xxx
    secret_key: xxx
    bucket: chanpy
    secure: false
    public_base: http://127.0.0.1:9000/chanpy   # 拼接外链用
"""
import os
import uuid

from Common.ChanException import CChanException, ErrCode


def minio_upload(path: str, conf: dict) -> str:
    try:
        from minio import Minio  # 懒加载,可选依赖
    except ImportError as e:
        raise CChanException("minio 后端需要 pip install minio", ErrCode.CONFIG_ERROR) from e
    client = Minio(
        conf.get("endpoint", "127.0.0.1:9000"),
        access_key=conf.get("access_key"),
        secret_key=conf.get("secret_key"),
        secure=bool(conf.get("secure", False)),
    )
    bucket = conf.get("bucket", "chanpy")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    obj_name = f"{uuid.uuid4().hex}{os.path.splitext(path)[1]}"
    client.fput_object(bucket, obj_name, path)
    base = conf.get("public_base")
    return f"{base.rstrip('/')}/{obj_name}" if base else client.presigned_get_object(bucket, obj_name)
