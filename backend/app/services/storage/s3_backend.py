"""火山引擎对象存储 TOS 后端（S3 兼容）—— 阶段 4 上线必需。

为什么必须：veFaaS 实例除 `/tmp` 外只读，且 `/tmp` 随实例重建清空。
业务数据（鞋柜 JSON）与资产（画稿图片）都必须落到对象存储，否则"数据会丢"。

实现要点（《部署笔记》第十三节 + 排错清单）：
- endpoint 用 `https://tos-s3-cn-beijing.volces.com`（注意 `tos-s3-` 前缀）
- 必须显式 `signature_version="s3v4"` + `addressing_style="virtual"`（否则报 InvalidPathAccess）
- key 仍然是"受控相对 key"（`owners/{owner_id}/...`），业务层零改动
- 单个对象 put 天然原子（覆盖写），因此 `archive.json` 的原子写语义得以保留
- 配合"函数最大实例数 = 1"使用：JSON 读-改-写不会并发覆盖
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.paths import safe_key
from app.services.storage.backend import KeyNotFound

# 这些错误码代表"对象不存在"，而不是故障
_NOT_FOUND_CODES = {"NoSuchKey", "404", "NotFound"}


class S3Backend:
    name = "s3"

    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("S3_ENDPOINT", settings.s3_endpoint),
                ("S3_BUCKET", settings.s3_bucket),
                ("S3_ACCESS_KEY", settings.s3_access_key),
                ("S3_SECRET_KEY", settings.s3_secret_key),
            )
            if not value
        ]
        if missing:
            raise AppError(
                ErrorCode.UPSTREAM_AUTH_FAILED,
                message="对象存储配置不完整，请补齐：" + "、".join(missing),
                detail={"missing": missing},
            )

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region or "cn-beijing",
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    # ---------------- 内部 ----------------
    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in _NOT_FOUND_CODES or status == 404

    def _wrap_error(self, exc: Exception, operation: str, key: str | None = None) -> AppError:
        detail: dict[str, Any] = {"operation": operation}
        if key:
            detail["key"] = key
        if isinstance(exc, ClientError):
            detail["upstream_code"] = str(exc.response.get("Error", {}).get("Code", ""))[:60]
        else:
            detail["reason"] = type(exc).__name__
        return AppError(ErrorCode.STORAGE_WRITE_FAILED, detail=detail)

    # ---------------- 协议 ----------------
    def put_bytes(self, key: str, data: bytes) -> None:
        normalized = safe_key(key)
        try:
            self.client.put_object(Bucket=self.bucket, Key=normalized, Body=data)
        except (ClientError, BotoCoreError) as exc:
            raise self._wrap_error(exc, "put_object", normalized) from exc

    def get_bytes(self, key: str) -> bytes:
        normalized = safe_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=normalized)
            return response["Body"].read()
        except ClientError as exc:
            if self._is_not_found(exc):
                raise KeyNotFound(normalized) from exc
            raise self._wrap_error(exc, "get_object", normalized) from exc
        except BotoCoreError as exc:
            raise self._wrap_error(exc, "get_object", normalized) from exc

    def exists(self, key: str) -> bool:
        normalized = safe_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=normalized)
            return True
        except ClientError as exc:
            if self._is_not_found(exc):
                return False
            raise self._wrap_error(exc, "head_object", normalized) from exc
        except BotoCoreError as exc:
            raise self._wrap_error(exc, "head_object", normalized) from exc

    def delete(self, key: str) -> bool:
        normalized = safe_key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=normalized)
            return True
        except (ClientError, BotoCoreError) as exc:
            raise self._wrap_error(exc, "delete_object", normalized) from exc

    def delete_prefix(self, prefix: str) -> int:
        normalized = prefix.rstrip("/")
        keys = self.list_keys(normalized)
        if not keys:
            return 0
        removed = 0
        try:
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
                removed += len(batch)
        except (ClientError, BotoCoreError) as exc:
            raise self._wrap_error(exc, "delete_objects", normalized) from exc
        return removed

    def list_keys(self, prefix: str = "") -> list[str]:
        normalized = safe_key(prefix).rstrip("/") if prefix else ""
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        try:
            request: dict[str, Any] = {"Bucket": self.bucket}
            if normalized:
                request["Prefix"] = normalized + "/"
            for page in paginator.paginate(**request):
                for item in page.get("Contents", []) or []:
                    key = item.get("Key")
                    if key:
                        keys.append(str(key))
        except (ClientError, BotoCoreError) as exc:
            raise self._wrap_error(exc, "list_objects_v2", normalized or None) from exc
        return sorted(keys)
