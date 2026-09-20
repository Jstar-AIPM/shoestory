"""状态机：允许的状态转换表（唯一真相）。

对应《第 1 阶段技术开发文档》6.4 的状态流转图。
- 新增状态只允许**追加**，不得复用旧状态语义；
- 非法转换一律 INVALID_STATE（409），不允许“悄悄跳过”。
"""

from __future__ import annotations

from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.schemas.enums import TaskState
from app.schemas.task import TaskRecord

S = TaskState

TRANSITIONS: dict[TaskState, set[TaskState]] = {
    S.CREATED: {S.RESOLVING, S.CANCELLED},
    S.RESOLVING: {
        S.MODEL_NOT_FOUND,
        S.RESOLVE_FAILED,
        S.AWAITING_SOURCE_CONFIRM,
        S.INTERRUPTED,
        S.CANCELLED,
    },
    S.MODEL_NOT_FOUND: {S.CANCELLED},
    # 搜图失败/型号没找到时，用户可改用“手动指定源图”继续 -> 允许直接进入预处理
    S.RESOLVE_FAILED: {S.AWAITING_SOURCE_CONFIRM, S.PREPROCESSING, S.CANCELLED},
    S.AWAITING_SOURCE_CONFIRM: {S.PREPROCESSING, S.CANCELLED},
    S.PREPROCESSING: {S.GENERATING, S.FAILED, S.INTERRUPTED, S.CANCELLED},
    S.GENERATING: {S.REFINING, S.FAILED, S.INTERRUPTED, S.CANCELLED},
    S.REFINING: {S.VERIFYING, S.FAILED, S.INTERRUPTED, S.CANCELLED},
    S.VERIFYING: {
        S.GENERATING,
        S.AWAITING_EFFECT_CONFIRM,
        S.FAILED,
        S.INTERRUPTED,
        S.CANCELLED,
    },
    S.INTERRUPTED: {S.PREPROCESSING, S.GENERATING, S.FAILED, S.CANCELLED},
    S.AWAITING_EFFECT_CONFIRM: {S.ARCHIVING, S.GENERATING, S.CANCELLED},
    S.ARCHIVING: {S.ARCHIVED, S.FAILED, S.INTERRUPTED, S.CANCELLED},
    S.ARCHIVED: set(),
    S.FAILED: {S.GENERATING, S.ARCHIVING, S.CANCELLED},
    S.CANCELLED: set(),
}

TERMINAL_STATES: set[TaskState] = {S.ARCHIVED, S.CANCELLED}


def can_transition(current: TaskState, target: TaskState) -> bool:
    return target in TRANSITIONS.get(current, set())


def transit(
    record: TaskRecord,
    target: TaskState,
    *,
    event: str | None = None,
    detail: dict | None = None,
) -> TaskRecord:
    if record.state == target:
        return record
    if not can_transition(record.state, target):
        raise AppError(
            ErrorCode.INVALID_STATE,
            detail={"from": record.state.value, "to": target.value},
        )
    previous = record.state
    record.state = target
    record.updated_at = now_iso()
    record.history.append(
        {
            "at": record.updated_at,
            "event": event or f"state:{target.value}",
            "from": previous.value,
            "to": target.value,
            "detail": detail or {},
        }
    )
    return record
