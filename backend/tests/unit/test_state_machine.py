"""状态机：允许/非法转换、终态、人工确认点不可被跳过。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.schemas.enums import TaskState as S
from app.schemas.task import TaskRecord
from app.services.workflow.state_machine import TRANSITIONS, can_transition, transit


def make_record(state: S = S.CREATED) -> TaskRecord:
    return TaskRecord(
        task_id="tk_test",
        owner_id="owner",
        state=state,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.CREATED, S.RESOLVING),
        (S.RESOLVING, S.AWAITING_SOURCE_CONFIRM),
        (S.RESOLVING, S.MODEL_NOT_FOUND),
        (S.RESOLVING, S.RESOLVE_FAILED),
        (S.AWAITING_SOURCE_CONFIRM, S.PREPROCESSING),
        (S.PREPROCESSING, S.GENERATING),
        (S.GENERATING, S.REFINING),
        (S.REFINING, S.VERIFYING),
        (S.VERIFYING, S.GENERATING),
        (S.VERIFYING, S.AWAITING_EFFECT_CONFIRM),
        (S.AWAITING_EFFECT_CONFIRM, S.GENERATING),
        (S.AWAITING_EFFECT_CONFIRM, S.ARCHIVING),
        (S.ARCHIVING, S.ARCHIVED),
        (S.FAILED, S.GENERATING),
        (S.INTERRUPTED, S.GENERATING),
    ],
)
def test_allowed_transitions(source: S, target: S) -> None:
    assert can_transition(source, target)
    record = make_record(source)
    transit(record, target, event="test")
    assert record.state == target
    assert record.history[-1]["event"] == "test"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.AWAITING_SOURCE_CONFIRM, S.ARCHIVED),  # 不能跳过生成/质检/确认
        (S.MODEL_NOT_FOUND, S.GENERATING),
        (S.AWAITING_SOURCE_CONFIRM, S.GENERATING),
        (S.CANCELLED, S.GENERATING),
        (S.ARCHIVED, S.GENERATING),
        (S.CREATED, S.ARCHIVED),
    ],
)
def test_illegal_transitions_raise(source: S, target: S) -> None:
    assert not can_transition(source, target)
    record = make_record(source)
    with pytest.raises(AppError) as excinfo:
        transit(record, target)
    assert excinfo.value.code is ErrorCode.INVALID_STATE
    assert record.state == source  # 失败时状态不被修改


def test_terminal_states_have_no_exit() -> None:
    assert TRANSITIONS[S.ARCHIVED] == set()
    assert TRANSITIONS[S.CANCELLED] == set()


def test_human_confirmation_states_are_stable() -> None:
    """两个人工确认点必须可以被“停留”，并且都是可恢复状态之外的。"""
    from app.services.storage.task_store import INTERRUPTIBLE_STATES

    assert S.AWAITING_SOURCE_CONFIRM not in INTERRUPTIBLE_STATES
    assert S.AWAITING_EFFECT_CONFIRM not in INTERRUPTIBLE_STATES
    assert S.AWAITING_SOURCE_CONFIRM in TRANSITIONS
    assert S.AWAITING_EFFECT_CONFIRM in TRANSITIONS
