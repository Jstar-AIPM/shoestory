"""鉴权与邀请码相关结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=4, max_length=64)

    @field_validator("code")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("邀请码不能为空")
        return cleaned


class LoginOut(BaseModel):
    owner_id: str
    role: str
    expires_at: str
    code_expires_at: str | None = None
    remaining: int | None = None
    message: str = ""


class MeOut(BaseModel):
    authenticated: bool
    owner_id: str | None = None
    role: str | None = None
    auth_required: bool = True
    remaining: int | None = None
    can_generate: bool = False
    code_expires_at: str | None = None
    message: str = ""


class CodeInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    owner_id: str
    role: str
    max_uses: int | None = None
    used_count: int = 0
    remaining: int | None = None
    expires_at: str | None = None
    status: str = "active"
    note: str = ""
    created_at: str = ""
    last_used_at: str | None = None
    expired: bool = False
    exhausted: bool = False
    archived_count: int = 0


class CodeListOut(BaseModel):
    total: int
    items: list[dict[str, Any]]


class CreateCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=120)
    #: 不传则用配置默认（20 次 / 30 天）
    max_uses: int | None = Field(default=None, ge=1, le=10_000)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


class CreateCodeOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    owner_id: str
    role: str
    max_uses: int | None = None
    used_count: int = 0
    remaining: int | None = None
    expires_at: str | None = None
    status: str = "active"
    note: str = ""


class PurgeOut(BaseModel):
    owner_id: str
    removed_files: int
    message: str = "该访客的数据已清理"
