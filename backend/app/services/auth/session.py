"""会话：签名 Cookie（替代"每次请求都输邀请码"）。

- 只存 `owner_id` + `role` + 过期时间，用 HMAC-SHA256 签名（密钥来自配置或首启自动生成）；
- **不做服务端会话表**：无状态、重启不丢、多实例安全；
- Cookie 属性：`HttpOnly`（JS 读不到）、`SameSite=Lax`、HTTPS 下 `Secure`；
- 会话有效期（默认 30 天）**长于**邀请码的额度生命周期 —— 这样"额度用完/码过期"后
  用户仍能以同一会话**查看已归档的鞋柜**，只是不能再生成。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.storage.atomic_io import read_json, write_json
from app.services.storage.backend import StorageBackend

COOKIE_NAME = "lvli_session"
SECRET_KEY = "system/secret.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass
class Session:
    owner_id: str
    role: str
    expires_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict:
        return {"owner_id": self.owner_id, "role": self.role, "expires_at": self.expires_at}


class SessionSigner:
    """签名/校验会话 Cookie。密钥优先取配置，否则首次启动生成并持久化。"""

    def __init__(self, backend: StorageBackend, settings: Settings) -> None:
        self.settings = settings
        self._secret = (settings.session_secret or "").encode("utf-8")
        if not self._secret:
            self._secret = self._load_or_create_secret(backend)

    @staticmethod
    def _load_or_create_secret(backend: StorageBackend) -> bytes:
        payload, _ = read_json(backend, SECRET_KEY)
        secret = (payload or {}).get("session_secret")
        if isinstance(secret, str) and len(secret) >= 32:
            return secret.encode("utf-8")
        generated = secrets.token_urlsafe(48)
        write_json(backend, SECRET_KEY, {"schema_version": 1, "session_secret": generated})
        return generated.encode("utf-8")

    # ---------------- 签发 / 校验 ----------------
    def issue(self, owner_id: str, role: str, *, ttl_days: int | None = None) -> Session:
        days = self.settings.session_ttl_days if ttl_days is None else ttl_days
        expires = _now() + timedelta(days=days)
        payload = {
            "owner_id": owner_id,
            "role": role,
            "exp": int(expires.timestamp()),
        }
        body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        signature = _b64(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        return Session(owner_id=owner_id, role=role, expires_at=expires.isoformat(timespec="seconds"))

    def sign_value(self, session: Session) -> str:
        payload = {
            "owner_id": session.owner_id,
            "role": session.role,
            "exp": int(datetime.fromisoformat(session.expires_at).timestamp()),
        }
        body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        signature = _b64(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def verify(self, value: str | None) -> Session | None:
        if not value or "." not in value:
            return None
        body, _, signature = value.partition(".")
        expected = _b64(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None  # 签名不对：当作未登录（不泄露原因）
        try:
            payload = json.loads(_unb64(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        owner_id = payload.get("owner_id")
        role = payload.get("role") or "guest"
        exp = payload.get("exp")
        if not isinstance(owner_id, str) or not isinstance(exp, int):
            return None
        if _now().timestamp() > exp:
            return None  # 会话过期
        return Session(
            owner_id=owner_id, role=role, expires_at=datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(timespec="seconds")
        )


def require_session(session: Session | None) -> Session:
    if session is None:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    return session


def require_admin(session: Session | None) -> Session:
    require_session(session)
    assert session is not None  # for type checkers
    if not session.is_admin:
        raise AppError(ErrorCode.FORBIDDEN)
    return session
