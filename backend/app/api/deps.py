"""API 依赖注入：配置、容器、当前身份。

身份（阶段 1–3）：统一从 `current_identity()` 取 owner_id —— 阶段 1 用 `DEV_OWNER_ID`，
阶段 4 改为“邀请码 -> owner_id”（cookie 仅用于免去重复输码，见内部工程笔记 4.7(2)）。
**业务代码不得自行读取环境变量拼身份。**
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.container import Container
from app.core.paths import validate_owner_id


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_settings(request: Request) -> Settings:
    return request.app.state.container.settings


def current_identity(request: Request) -> str:
    """返回当前请求的 owner_id（阶段 1–3 = DEV_OWNER_ID）。"""
    settings: Settings = request.app.state.container.settings
    # 阶段 4 在此处改为：从签名 cookie / 邀请码会话解析 owner_id；无凭证 -> 401
    owner_id = settings.dev_owner_id
    return validate_owner_id(owner_id)
