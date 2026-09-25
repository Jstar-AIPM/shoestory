"""API 依赖注入：配置、容器、当前身份（阶段 4：邀请码会话）。

身份来源（一个邀请码 = 一个鞋柜，见 services/auth/invite_store.py）：
- **prod**：必须持有效会话 Cookie，`owner_id` 由邀请码派生（一码一鞋柜）；
- **dev**：默认用 `DEV_OWNER_ID`（不强制登录，便于本地开发）；可用 `FORCE_AUTH=true` 打开登录做测试。

业务代码一律通过 `current_identity()` 取身份，**不得自行读环境变量拼身份**。
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.container import Container
from app.core.paths import validate_owner_id
from app.services.auth.session import COOKIE_NAME, Session, require_admin, require_session

#: 本地开发且未启用强制登录时，管理接口允许直接调用（仅 dev；prod 一律要求管理员会话）
DEV_ADMIN_BYPASS = True


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_settings(request: Request) -> Settings:
    return request.app.state.container.settings


def current_session(request: Request) -> Session | None:
    """读取并校验会话 Cookie；无/伪造/过期一律返回 None（不泄露原因）。"""
    container = get_container(request)
    return container.session_signer.verify(request.cookies.get(COOKIE_NAME))


def current_identity(request: Request) -> str:
    settings = get_settings(request)
    if settings.auth_required:
        session = require_session(current_session(request))
        return validate_owner_id(session.owner_id)
    return validate_owner_id(settings.dev_owner_id)


def require_admin_session(request: Request) -> Session | None:
    settings = get_settings(request)
    if not settings.auth_required and DEV_ADMIN_BYPASS and settings.env == "dev":
        # 本地开发便捷通道（prod 永不生效，因为 prod 下 auth_required 恒为 True）
        return None
    return require_admin(current_session(request))
