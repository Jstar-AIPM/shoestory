"""S3/TOS 后端契约测试（用假客户端，不联网、不花钱）。

真实验证（连真实桶）在阶段 4 的部署验证里做；这里保证：
- 参数是否正确（s3v4 + virtual addressing + 正确 endpoint）—— 这是排错清单里的高频坑；
- key 是否仍是受控相对路径；
- 错误映射：对象不存在 → KeyNotFound；其他错误 → STORAGE_WRITE_FAILED（不泄露上游原文）。
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.storage.backend import KeyNotFound
from app.services.storage.s3_backend import S3Backend


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeClient:
    """最小 S3 假实现：内存字典 + 可注入错误。"""

    instances: list["_FakeClient"] = []
    created_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeClient.created_kwargs = kwargs
        self.objects: dict[str, bytes] = {}
        self.raises: ClientError | None = None
        _FakeClient.instances.append(self)

    # --- 内部 ---
    def _boom(self) -> None:
        if self.raises:
            raise self.raises

    @staticmethod
    def _not_found(key: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject"
        )

    # --- S3 API 子集 ---
    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict:
        self._boom()
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:
        self._boom()
        if Key not in self.objects:
            raise self._not_found(Key)
        return {"Body": _FakeBody(self.objects[Key])}

    def head_object(self, Bucket: str, Key: str) -> dict:
        self._boom()
        if Key not in self.objects:
            raise self._not_found(Key)
        return {}

    def delete_object(self, Bucket: str, Key: str) -> dict:
        self._boom()
        self.objects.pop(Key, None)
        return {}

    def delete_objects(self, Bucket: str, Delete: dict) -> dict:
        self._boom()
        for item in Delete.get("Objects", []):
            self.objects.pop(item["Key"], None)
        return {}

    def get_paginator(self, name: str):
        outer = self

        class _Paginator:
            def paginate(self, Bucket: str, Prefix: str | None = None):
                keys = sorted(
                    k for k in outer.objects if (Prefix is None or k.startswith(Prefix))
                )
                yield {"Contents": [{"Key": k} for k in keys]}

        return _Paginator()


@pytest.fixture
def backend(monkeypatch) -> S3Backend:
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: _FakeClient(**kwargs))
    settings = Settings(
        _env_file=None,
        storage_provider="s3",
        s3_endpoint="https://tos-s3-cn-beijing.volces.com",
        s3_bucket="lvli-test",
        s3_region="cn-beijing",
        s3_access_key="AK",
        s3_secret_key="SK",
    )
    return S3Backend(settings)


def test_client_uses_s3v4_and_virtual_addressing(monkeypatch) -> None:
    """排错清单里的高频坑：签名版本与寻址风格不对会报 InvalidPathAccess。"""
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: _FakeClient(**kwargs))
    settings = Settings(
        _env_file=None,
        storage_provider="s3",
        s3_endpoint="https://tos-s3-cn-beijing.volces.com",
        s3_bucket="b",
        s3_access_key="AK",
        s3_secret_key="SK",
    )
    S3Backend(settings)
    kwargs = _FakeClient.created_kwargs
    assert kwargs["endpoint_url"] == "https://tos-s3-cn-beijing.volces.com"
    assert kwargs["config"].signature_version == "s3v4"
    assert kwargs["config"].s3 == {"addressing_style": "virtual"}


def test_missing_config_fails_fast() -> None:
    with pytest.raises(AppError) as excinfo:
        S3Backend(Settings(_env_file=None, storage_provider="s3", s3_bucket=""))
    assert excinfo.value.code is ErrorCode.UPSTREAM_AUTH_FAILED
    assert "S3_BUCKET" in str(excinfo.value.detail)


def test_put_get_exists_delete_roundtrip(backend: S3Backend) -> None:
    key = "owners/owner/archive.json"
    backend.put_bytes(key, b'{"schema_version": 1}')

    assert backend.exists(key) is True
    assert backend.get_bytes(key) == b'{"schema_version": 1}'
    assert backend.delete(key) is True
    assert backend.exists(key) is False


def test_get_missing_raises_key_not_found(backend: S3Backend) -> None:
    with pytest.raises(KeyNotFound):
        backend.get_bytes("owners/nobody/archive.json")


def test_keys_stay_controlled_relative(backend: S3Backend) -> None:
    """业务层仍然只说相对 key —— 换后端不需要改任何业务代码。"""
    backend.put_bytes("owners/ow_1a2b/tasks/tk_1.json", b"{}")
    keys = backend.list_keys("owners/ow_1a2b")
    assert keys == ["owners/ow_1a2b/tasks/tk_1.json"]


def test_traversal_key_rejected(backend: S3Backend) -> None:
    with pytest.raises(AppError) as excinfo:
        backend.put_bytes("../escape.json", b"x")
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_delete_prefix_removes_only_that_owner(backend: S3Backend) -> None:
    backend.put_bytes("owners/a/assets/sh1/artwork.png", b"a1")
    backend.put_bytes("owners/a/archive.json", b"a2")
    backend.put_bytes("owners/b/archive.json", b"b1")

    removed = backend.delete_prefix("owners/a")
    assert removed == 2
    assert backend.list_keys("owners/a") == []
    assert backend.list_keys("owners/b") == ["owners/b/archive.json"]


def test_upstream_error_is_wrapped_without_leaking(backend: S3Backend) -> None:
    client = _FakeClient.instances[-1]
    client.raises = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "secret-ish upstream detail"},
         "ResponseMetadata": {"HTTPStatusCode": 403}},
        "PutObject",
    )
    with pytest.raises(AppError) as excinfo:
        backend.put_bytes("owners/a/archive.json", b"x")
    assert excinfo.value.code is ErrorCode.STORAGE_WRITE_FAILED
    assert "secret-ish upstream detail" not in str(excinfo.value.detail)
    assert excinfo.value.detail["upstream_code"] == "AccessDenied"
