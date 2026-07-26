"""腾讯云 COS 图床后端(可选依赖 pip install cos-python-sdk-v5)

config.yaml 配置示例:
cos:
  backend: txcos
  txcos:
    secret_id: xxx
    secret_key: xxx
    region: ap-guangzhou
    bucket: chanpy-125xxxxxxx
"""
import os
import uuid

from Common.ChanException import CChanException, ErrCode


def txcos_upload(path: str, conf: dict) -> str:
    try:
        from qcloud_cos import CosConfig, CosS3Client  # 懒加载,可选依赖
    except ImportError as e:
        raise CChanException("txcos 后端需要 pip install cos-python-sdk-v5", ErrCode.CONFIG_ERROR) from e
    region = conf.get("region", "ap-guangzhou")
    bucket = conf.get("bucket")
    client = CosS3Client(CosConfig(
        Region=region, SecretId=conf.get("secret_id"), SecretKey=conf.get("secret_key")))
    obj_name = f"{uuid.uuid4().hex}{os.path.splitext(path)[1]}"
    client.upload_file(Bucket=bucket, LocalFilePath=path, Key=obj_name)
    return f"https://{bucket}.cos.{region}.myqcloud.com/{obj_name}"
