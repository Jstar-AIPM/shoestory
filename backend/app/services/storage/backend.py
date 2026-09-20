"""存储抽象（阶段 1 强制项）：业务层只说“相对 key”，落地由后端决定。

阶段 1 只实现 LocalBackend；阶段 4 增加 S3Backend（火山 TOS）后仅改环境变量
`STORAGE_PROVIDER=s3`，业务代码零改动（内部工程笔记 4.7(1)）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.config import Settings


class KeyNotFound(KeyError):
    """受控 key 在存储中不存在。"""


@runtime_checkable
class StorageBackend(Protocol):
    name: str

    def put_bytes(self, key: str, data: bytes) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...


def build_backend(settings: Settings) -> StorageBackend:
    if settings.storage_provider == "local":
        from app.services.storage.local_backend import LocalBackend

        return LocalBackend(settings.data_root)
    if settings.storage_provider == "s3":
        from app.services.storage.s3_backend import S3Backend

        return S3Backend(settings)
    raise ValueError(f"未知的 STORAGE_PROVIDER: {settings.storage_provider}")
