"""任务持久化与恢复：重启后“跑一半”的任务变 interrupted，人工确认点原样保留。"""

from __future__ import annotations

from app.core.idgen import now_iso
from app.schemas.enums import TaskState as S
from app.schemas.task import TaskRecord
from app.services.storage.local_backend import LocalBackend
from app.services.storage.task_store import TaskStore
from app.services.workflow.recovery import recover_on_startup


def make_record(task_id: str, state: S) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        owner_id="owner",
        state=state,
        created_at=now_iso(),
        updated_at=now_iso(),
        query="kd12",
        style_id="bw_lineart",
    )


def test_running_task_becomes_interrupted(tmp_path) -> None:
    backend = LocalBackend(tmp_path / "data")
    store = TaskStore(backend)
    store.create(make_record("tk_generating", S.GENERATING))

    marked = recover_on_startup(store)

    assert marked == ["tk_generating"]
    record = store.get("owner", "tk_generating")
    assert record.state is S.INTERRUPTED
    assert record.history[-1]["event"] == "interrupted_by_restart"
    assert record.progress["step"] == "interrupted"


def test_human_confirmation_points_survive_restart(tmp_path) -> None:
    backend = LocalBackend(tmp_path / "data")
    store = TaskStore(backend)
    store.create(make_record("tk_source", S.AWAITING_SOURCE_CONFIRM))
    store.create(make_record("tk_effect", S.AWAITING_EFFECT_CONFIRM))
    store.create(make_record("tk_archived", S.ARCHIVED))

    marked = recover_on_startup(store)

    assert marked == []
    assert store.get("owner", "tk_source").state is S.AWAITING_SOURCE_CONFIRM
    assert store.get("owner", "tk_effect").state is S.AWAITING_EFFECT_CONFIRM
    assert store.get("owner", "tk_archived").state is S.ARCHIVED


def test_interrupted_task_can_continue(tmp_path) -> None:
    """恢复后可以继续：状态可回到 generating（状态机允许）。"""
    from app.services.workflow.state_machine import transit

    backend = LocalBackend(tmp_path / "data")
    store = TaskStore(backend)
    store.create(make_record("tk_resume", S.GENERATING))
    recover_on_startup(store)

    record = store.get("owner", "tk_resume")
    transit(record, S.GENERATING, event="resume")
    store.save(record)
    assert store.get("owner", "tk_resume").state is S.GENERATING


def test_cross_owner_task_access_is_404(tmp_path) -> None:
    from app.core.errors import AppError, ErrorCode

    backend = LocalBackend(tmp_path / "data")
    store = TaskStore(backend)
    store.create(make_record("tk_owner_a", S.AWAITING_EFFECT_CONFIRM))

    try:
        store.get("owner_b", "tk_owner_a")
    except AppError as exc:
        assert exc.code is ErrorCode.TASK_NOT_FOUND
    else:  # pragma: no cover
        raise AssertionError("跨 owner 读取必须 404")
