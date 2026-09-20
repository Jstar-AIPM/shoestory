"""火山引擎对象存储 TOS 后端 —— 阶段 4 实现（阶段 1 仅留接口桩）。

阶段 4 实现要点（《部署笔记》第十三节）：
- S3 兼容协议：endpoint = https://tos-s3-cn-beijing.volces.com
- 必须显式 signature_version="s3v4" 且 addressing_style="virtual"
- 桶名小写字母/数字/连字符，全局唯一
- 配置来自环境变量：STORAGE_PROVIDER=s3 / S3_ENDPOINT / S3_BUCKET / S3_REGION / S3_ACCESS_KEY / S3_SECRET_KEY
- veFaaS 实例除 /tmp 外只读，因此线上必须走本后端（图片 + 档案 JSON 全部落 TOS）
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.storage.backend import KeyNotFound

_NOT_IMPLEMENTED_MSG = (
    "对象存储后端将在阶段 4（上线部署）实现。当前阶段请保持 STORAGE_PROVIDER=local。"
)


class S3Backend:
    name = "s3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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
            )

    def put_bytes(self, key: str, data: bytes) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_bytes(self, key: str) -> bytes:
        raise KeyNotFound(key)

    def exists(self, key: str) -> bool:
        return False

    def delete(self, key: str) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def delete_prefix(self, prefix: str) -> int:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def list_keys(self, prefix: str = "") -> list[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
