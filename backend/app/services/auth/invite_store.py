"""邀请码存储（阶段 4 上线必需）。

设计（对应内部工程笔记 4.7(2) 的最终形态）：
- **一个邀请码 = 一个鞋柜**：`owner_id` 由邀请码确定性派生（同码永远同一鞋柜，换设备登录也能回到自己的鞋柜）
- 普通码：有效期 30 天 / 上限 20 次生成；**1 次 = 点击一次生成（手动"重新生成"也算）**，
  质检自动重试**不计数**（否则质检不稳会白白吃掉面试官额度）
- 管理员码：不限次数、不过期、**不可作废/删除**（避免把自己锁在门外）
- 额度用完/过期后：**已归档的鞋柜仍可查看**（只有"生成"需要额度）
- 存储位置：`system/invite_codes.json`（全局，不属于任何 owner）
- 并发：写操作单写者锁 + 部署时限制函数最大实例数 = 1（见部署方案）
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.storage.atomic_io import read_json, write_json
from app.services.storage.backend import StorageBackend

STORE_KEY = "system/invite_codes.json"
SCHEMA_VERSION = 1

_lock = threading.RLock()


def owner_id_for_code(code: str) -> str:
    """由邀请码确定性派生 owner_id：同码 = 同一鞋柜。"""
    digest = hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
    return f"ow_{digest[:10]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class InviteCode:
    code: str
    owner_id: str
    role: str  # "guest" | "admin"
    max_uses: int | None
    used_count: int
    expires_at: str | None
    status: str  # "active" | "revoked"
    note: str
    created_at: str
    last_used_at: str | None

    @property
    def unlimited(self) -> bool:
        return self.max_uses is None

    @property
    def remaining(self) -> int | None:
        return None if self.unlimited else max(0, (self.max_uses or 0) - self.used_count)

    def is_admin(self) -> bool:
        return self.role == "admin"

    def expired(self) -> bool:
        expiry = _parse(self.expires_at)
        return bool(expiry and _now() > expiry)

    def exhausted(self) -> bool:
        return not self.unlimited and self.used_count >= (self.max_uses or 0)

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "owner_id": self.owner_id,
            "role": self.role,
            "max_uses": self.max_uses,
            "used_count": self.used_count,
            "remaining": self.remaining,
            "expires_at": self.expires_at,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expired": self.expired(),
            "exhausted": self.exhausted(),
        }


class InviteStore:
    def __init__(self, backend: StorageBackend, settings: Settings) -> None:
        self.backend = backend
        self.settings = settings

    # ---------------- 读写 ----------------
    def _load(self) -> list[InviteCode]:
        payload, _corrupted = read_json(self.backend, STORE_KEY)
        if not payload:
            return []
        items = payload.get("codes") or []
        codes: list[InviteCode] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            codes.append(
                InviteCode(
                    code=str(item["code"]),
                    owner_id=str(item.get("owner_id") or owner_id_for_code(str(item["code"]))),
                    role=str(item.get("role") or "guest"),
                    max_uses=item.get("max_uses") if item.get("max_uses") is not None else None,
                    used_count=int(item.get("used_count") or 0),
                    expires_at=item.get("expires_at"),
                    status=str(item.get("status") or "active"),
                    note=str(item.get("note") or ""),
                    created_at=str(item.get("created_at") or _iso(_now())),
                    last_used_at=item.get("last_used_at"),
                )
            )
        return codes

    def _save(self, codes: list[InviteCode]) -> None:
        write_json(
            self.backend,
            STORE_KEY,
            {
                "schema_version": SCHEMA_VERSION,
                "updated_at": _iso(_now()),
                "codes": [c.public_dict() | {"expired": None, "exhausted": None, "remaining": c.remaining} for c in codes],
            },
        )

    # ---------------- 查询 ----------------
    def list_all(self) -> list[InviteCode]:
        return self._load()

    def find_by_code(self, code: str) -> InviteCode | None:
        wanted = code.strip().upper()
        for item in self._load():
            if item.code.upper() == wanted:
                return item
        return None

    def find_by_owner(self, owner_id: str) -> InviteCode | None:
        for item in self._load():
            if item.owner_id == owner_id:
                return item
        return None

    # ---------------- 业务 ----------------
    def create(
        self,
        *,
        note: str = "",
        max_uses: int | None = None,
        ttl_days: int | None = None,
        role: str = "guest",
        code: str | None = None,
        protected_unlimited: bool = False,
    ) -> InviteCode:
        with _lock:
            codes = self._load()
            new_code = (code or secrets.token_hex(4).upper()).upper()
            if any(c.code.upper() == new_code for c in codes):
                raise AppError(ErrorCode.INVALID_INPUT, message="这个邀请码已存在，请换一个。")
            if protected_unlimited:
                max_uses_value: int | None = None
                expires = None
                role = "admin"
            else:
                max_uses_value = self.settings.invite_code_max_uses if max_uses is None else max_uses
                days = self.settings.invite_code_ttl_days if ttl_days is None else ttl_days
                expires = _iso(_now() + timedelta(days=days))
            record = InviteCode(
                code=new_code,
                owner_id=owner_id_for_code(new_code),
                role=role,
                max_uses=max_uses_value,
                used_count=0,
                expires_at=expires,
                status="active",
                note=note,
                created_at=_iso(_now()),
                last_used_at=None,
            )
            codes.append(record)
            self._save(codes)
            return record

    def authenticate(self, code: str) -> InviteCode:
        """校验邀请码本身是否可用（登录用）——**不消耗生成次数**。"""
        record = self.find_by_code(code)
        if not record:
            raise AppError(ErrorCode.CODE_INVALID)
        if record.status != "active":
            raise AppError(ErrorCode.CODE_EXPIRED, message="这个邀请码已被作废。")
        if record.expired():
            raise AppError(ErrorCode.CODE_EXPIRED)
        return record

    def consume_generation(self, owner_id: str) -> InviteCode:
        """消耗 1 次生成额度（创建任务与手动"重新生成"时各调一次）。

        - 管理员码：不计数
        - 额度用完 / 已过期 / 已作废：抛业务错误（前端据此提示，但**已归档的鞋柜仍可查看**）
        """
        with _lock:
            codes = self._load()
            for item in codes:
                if item.owner_id != owner_id:
                    continue
                if item.is_admin():
                    return item
                if item.status != "active":
                    raise AppError(ErrorCode.CODE_EXPIRED, message="这个邀请码已被作废。")
                if item.expired():
                    raise AppError(ErrorCode.CODE_EXPIRED)
                if item.exhausted():
                    raise AppError(ErrorCode.QUOTA_EXCEEDED)
                item.used_count += 1
                item.last_used_at = _iso(_now())
                self._save(codes)
                return item
        # 没找到对应邀请码：本地开发用 DEV_OWNER_ID 时会出现，视为不限额
        raise AppError(ErrorCode.FORBIDDEN, message="当前身份没有对应的邀请码。")

    def revoke(self, code: str) -> InviteCode:
        with _lock:
            codes = self._load()
            for item in codes:
                if item.code.upper() != code.strip().upper():
                    continue
                if item.is_admin():
                    # 硬保护：管理员码不可作废，否则会把自己锁在门外
                    raise AppError(
                        ErrorCode.FORBIDDEN,
                        message="管理员码不能作废（否则你自己的鞋柜会进不去）。",
                    )
                item.status = "revoked"
                self._save(codes)
                return item
        raise AppError(ErrorCode.CODE_INVALID)

    def bootstrap_from_env(self) -> list[str]:
        """首次启动时把 INVITE_CODES / ADMIN_CODE 环境变量里的码落到存储（已存在则跳过）。"""
        created: list[str] = []
        with _lock:
            existing = {c.code.upper() for c in self._load()}
            admin_code = (self.settings.admin_code or "").strip()
            if admin_code and admin_code.upper() not in existing:
                self.create(code=admin_code, note="管理员码（来自环境变量）", protected_unlimited=True)
                created.append(admin_code)

            for raw in (self.settings.invite_codes or "").split(","):
                candidate = raw.strip()
                if not candidate or candidate.upper() in existing:
                    continue
                self.create(code=candidate, note="初始邀请码（来自环境变量）")
                created.append(candidate)
        return created
