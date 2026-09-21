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
