"""Optional upload failures are visible but never expose transport/configuration secrets."""
import sys
import traceback
from types import ModuleType, SimpleNamespace

import pytest

from Common.ChanException import CChanException, ErrCode
import Plot.CosApi as cos


SECRET = "SYNTHETIC_PRIVATE_COS_CREDENTIAL_RESPONSE"


@pytest.fixture(params=["minio", "txcos"])
def transport(request, monkeypatch, tmp_path):
    state = {"calls": [], "fail_at": None, "failure": RuntimeError(SECRET)}
    def touch(point):
        state["calls"].append(point)
        if state["fail_at"] == point:
            raise state["failure"]
    image = tmp_path/"synthetic.png"
    image.write_bytes(b"synthetic image bytes, not private user content")
    if request.param == "minio":
        class CMinio:
            def __init__(self, endpoint, *, access_key, secret_key, secure):
                touch("construct")

            def bucket_exists(self, bucket):
                touch("bucket")
                return True

            def make_bucket(self, bucket):
                pytest.fail("existing fixture bucket must not be created")

            def fput_object(self, bucket, object_name, path):
                touch("upload")
                assert path == str(image)
                return SimpleNamespace(bucket_name=bucket, object_name=object_name, etag="synthetic-etag", version_id=None)

            def presigned_get_object(self, bucket, object_name):
                touch("presign")
                return state.get("presigned_result", "https://images.example.invalid/"+object_name+"?token="+SECRET)
        module = ModuleType("minio")
        module.Minio = CMinio
        monkeypatch.setitem(sys.modules, "minio", module)
        options = {"endpoint": "synthetic.example.invalid:9000", "access_key": SECRET, "secret_key": SECRET,
                   "bucket": "synthetic", "secure": True, "public_base": "https://images.example.invalid/synthetic"}
    else:
        def config(*, Region, SecretId, SecretKey):
            return SimpleNamespace(region=Region, secret_id=SecretId, secret_key=SecretKey)
        class CClient:
            def __init__(self, config):
                touch("construct")

            def upload_file(self, *, Bucket, LocalFilePath, Key):
                touch("upload")
                assert LocalFilePath == str(image)
                return {"ETag": "synthetic-etag"}
        module = ModuleType("qcloud_cos")
        module.CosConfig, module.CosS3Client = config, CClient
        monkeypatch.setitem(sys.modules, "qcloud_cos", module)
        options = {"secret_id": SECRET, "secret_key": SECRET, "region": "synthetic-region", "bucket": "synthetic-bucket"}
    configured = {"backend": request.param, request.param: options}
    reads = []
    def global_config():
        reads.append(True)
        return configured
    monkeypatch.setattr(cos, "get_cos_conf", global_config)
    return SimpleNamespace(backend=request.param, options=options, configured=configured,
                           state=state, image=image, reads=reads)


def test_explicit_empty_configuration_never_falls_back_to_a_remote_global_backend(transport):
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf={})
    assert error.value.errcode == ErrCode.CONFIG_ERROR
    assert transport.reads == [] and transport.state["calls"] == []


@pytest.mark.parametrize("point", ["construct", "upload"])
def test_sdk_failure_is_redacted_visible_and_never_retried(transport, point, capsys):
    transport.state["fail_at"] = point
    original = transport.image.read_bytes()
    with pytest.raises(CChanException) as error:
        try:
            cos.upload_file(str(transport.image), conf=transport.configured)
        except CChanException:
            formatted = traceback.format_exc()
            raise
    assert error.value.errcode == ErrCode.PLOT_ERR
    assert "图床" in str(error.value)
    assert SECRET not in formatted+str(error.value)+repr(error.value)+str(capsys.readouterr())
    assert transport.reads == [] and transport.state["calls"].count(point) == 1
    assert transport.image.read_bytes() == original


@pytest.mark.parametrize("bad", [False, 0, [], SECRET, {"backend": None}, {"backend": []},
                                 {"backend": SECRET}, {"backend": "minio", "minio": None},
                                 {"backend": "txcos", "txcos": SECRET}])
def test_invalid_explicit_config_is_redacted_without_global_lookup_or_sdk_io(transport, bad, capsys):
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf=bad)
    assert error.value.errcode == ErrCode.CONFIG_ERROR
    assert SECRET not in str(error.value)+str(capsys.readouterr())
    assert transport.reads == [] and transport.state["calls"] == []


def test_success_keeps_original_file_and_url_return_contract_with_implicit_lookup_only_for_none(transport, capsys):
    original = transport.image.read_bytes()
    url = cos.upload_file(str(transport.image))
    assert transport.reads == [True] and transport.state["calls"].count("upload") == 1
    assert type(url) is str and url.startswith("https://") and url.endswith(".png")
    assert transport.image.read_bytes() == original
    assert SECRET not in str(capsys.readouterr())


def test_interrupt_is_not_converted_to_success_or_a_retry(transport):
    transport.state.update(fail_at="upload", failure=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        cos.upload_file(str(transport.image), conf=transport.configured)
    assert transport.state["calls"].count("upload") == 1


def test_global_configuration_load_failure_is_redacted_before_any_sdk_use(transport, monkeypatch, capsys):
    def broken_config():
        raise RuntimeError(SECRET)
    monkeypatch.setattr(cos, "get_cos_conf", broken_config)
    with pytest.raises(CChanException) as error:
        try:
            cos.upload_file(str(transport.image))
        except CChanException:
            formatted = traceback.format_exc()
            raise
    assert error.value.errcode == ErrCode.CONFIG_ERROR
    assert SECRET not in formatted+str(error.value)+str(capsys.readouterr())
    assert transport.state["calls"] == []


def test_missing_optional_sdk_is_a_visible_redacted_failure_not_a_fallback(transport, monkeypatch):
    module = "minio" if transport.backend == "minio" else "qcloud_cos"
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf=transport.configured)
    assert error.value.errcode == ErrCode.CONFIG_ERROR
    assert transport.reads == [] and transport.state["calls"] == []


def test_typed_backend_config_error_keeps_its_code_but_not_its_private_message(transport, capsys):
    transport.state.update(fail_at="upload", failure=CChanException(SECRET, ErrCode.CONFIG_ERROR))
    with pytest.raises(CChanException) as error:
        try:
            cos.upload_file(str(transport.image), conf=transport.configured)
        except CChanException:
            formatted = traceback.format_exc()
            raise
    assert error.value.errcode == ErrCode.CONFIG_ERROR
    assert SECRET not in formatted+str(error.value)+str(capsys.readouterr())
    assert transport.state["calls"].count("upload") == 1


@pytest.mark.parametrize("transport", ["minio"], indirect=True)
def test_minio_presigned_url_is_returned_but_never_logged(transport, capsys):
    del transport.options["public_base"]
    url = cos.upload_file(str(transport.image), conf=transport.configured)
    assert url.startswith("https://images.example.invalid/") and url.endswith("?token="+SECRET)
    assert transport.state["calls"].count("presign") == 1
    assert SECRET not in str(capsys.readouterr())


@pytest.mark.parametrize("transport", ["minio"], indirect=True)
def test_minio_presign_failure_is_not_an_upload_success_or_exposed_secret(transport):
    del transport.options["public_base"]
    transport.state["fail_at"] = "presign"
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf=transport.configured)
    assert SECRET not in str(error.value)
    assert transport.state["calls"].count("upload") == 1 and transport.state["calls"].count("presign") == 1


@pytest.mark.parametrize("transport", ["minio"], indirect=True)
def test_minio_bucket_lookup_failure_is_redacted_and_never_writes(transport):
    transport.state["fail_at"] = "bucket"
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf=transport.configured)
    assert SECRET not in str(error.value)
    assert transport.state["calls"].count("bucket") == 1 and "upload" not in transport.state["calls"]


@pytest.mark.parametrize("transport", ["minio"], indirect=True)
@pytest.mark.parametrize("bad", [None, "", b"not-a-URL-string"])
def test_missing_or_wrong_type_presigned_url_is_never_returned_as_success(transport, bad):
    del transport.options["public_base"]
    transport.state["presigned_result"] = bad
    with pytest.raises(CChanException) as error:
        cos.upload_file(str(transport.image), conf=transport.configured)
    assert error.value.errcode == ErrCode.PLOT_ERR
    assert transport.state["calls"].count("upload") == 1 and transport.state["calls"].count("presign") == 1
