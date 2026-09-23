"""额度门：生成类操作消耗 1 次邀请码额度。

规则（与内部工程笔记 4.7(2) 一致）：
- **1 次 = 点击一次"生成"**；手动"重新生成"也算 1 次；
- 质检自动重试、选源图、归档、编辑、查看**都不计数**；
- 本地开发（未启用强制登录）不受限，便于调试。
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.auth.invite_store import InviteStore


def consume_generation(settings: Settings, store: InviteStore, owner_id: str) -> None:
    if not settings.auth_required:
        return
    store.consume_generation(owner_id)


# ---------------------------------------------------------------------------
# 体检护栏（V2 新增）
# ---------------------------------------------------------------------------
# 上传图体检会调用一次视觉模型（本机计算）。它不是"生成"，不消耗邀请码额度，
# 但要防"手滑反复上传"把成本刷起来。做法：进程内按天计数。
# 与部署形态一致：线上最大实例数 = 1，因此进程内计数就是全局计数。
_INSPECT_USAGE: dict[str, tuple[str, int]] = {}   # owner_id -> (日期, 次数)


def consume_inspect(settings: Settings, owner_id: str, *, today: str) -> None:
    """记一次体检；超过 ``MAX_INSPECT_PER_DAY`` 抛 QUOTA_EXCEEDED。"""
    if not settings.auth_required:
        return
    limit = settings.max_inspect_per_day
    day, used = _INSPECT_USAGE.get(owner_id, (today, 0))
    if day != today:
        day, used = today, 0
    if limit > 0 and used >= limit:
        from app.core.errors import AppError, ErrorCode

        raise AppError(
            ErrorCode.QUOTA_EXCEEDED,
            detail={"scope": "inspect", "limit": limit, "used": used},
        )
    _INSPECT_USAGE[owner_id] = (day, used + 1)


def inspect_usage(owner_id: str) -> int:
    return _INSPECT_USAGE.get(owner_id, ("", 0))[1]
