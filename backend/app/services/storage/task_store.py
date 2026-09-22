"""任务存储：`owners/{owner_id}/tasks/{task_id}.json`（含两个人工确认点）。

工程约定：长时间任务必须保存可恢复的任务状态，不能只依赖内存变量。
"""

from __future__ import annotations

import threading

from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.core.paths import owner_key
from app.schemas.enums import TaskState
from app.schemas.task import TaskRecord
from app.services.storage.atomic_io import read_json, write_json
from app.services.storage.backend import StorageBackend

SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA = 1

#: 这些状态表示“正在跑”，进程重启后统一置为 interrupted（人工确认点不在其中）
INTERRUPTIBLE_STATES = {
    TaskState.RESOLVING,
    TaskState.SEARCHING_SOURCE,
    TaskState.PREPROCESSING,
    TaskState.GENERATING,
    TaskState.REFINING,
    TaskState.VERIFYING,
    TaskState.ARCHIVING,
}

TERMINAL_STATES = {TaskState.ARCHIVED, TaskState.CANCELLED}

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.RLock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.RLock()
        return _locks[key]


def task_key(owner_id: str, task_id: str) -> str:
    return owner_key(owner_id, "tasks", f"{task_id}.json")


class TaskStore:
    def __init__(self, backend: StorageBackend) -> None:
        self.backend = backend

    def create(self, record: TaskRecord) -> TaskRecord:
        self.save(record)
        return record

    def get(self, owner_id: str, task_id: str) -> TaskRecord:
        key = task_key(owner_id, task_id)
        payload, corrupted = read_json(self.backend, key)
        if payload is None:
            raise AppError(ErrorCode.TASK_NOT_FOUND)
        version = int(payload.get("schema_version", SCHEMA_VERSION))
        if version > MAX_SUPPORTED_SCHEMA:
            raise AppError(ErrorCode.SCHEMA_TOO_NEW, detail={"found": version})
        try:
            record = TaskRecord.model_validate(payload)
        except Exception as exc:
            if corrupted:
                raise AppError(ErrorCode.STORAGE_CORRUPT) from exc
            raise
        if record.owner_id != owner_id:
            # 跨 owner 一律 404，不泄露“存在但无权限”
            raise AppError(ErrorCode.TASK_NOT_FOUND)
        return record

    def save(self, record: TaskRecord) -> None:
        record.updated_at = now_iso()
        record.schema_version = SCHEMA_VERSION
        key = task_key(record.owner_id, record.task_id)
        with _lock_for(key):
            write_json(self.backend, key, record)

    def list_owner(self, owner_id: str) -> list[TaskRecord]:
        prefix = owner_key(owner_id, "tasks") + "/"
        out: list[TaskRecord] = []
        for key in self.backend.list_keys(prefix):
            if not key.endswith(".json"):
                continue
            payload, _ = read_json(self.backend, key)
            if payload is None:
                continue
            try:
                out.append(TaskRecord.model_validate(payload))
            except Exception:
                continue
        return out

    def list_all(self) -> list[TaskRecord]:
        out: list[TaskRecord] = []
        for key in self.backend.list_keys("owners"):
            if "/tasks/" not in key or not key.endswith(".json"):
                continue
            payload, _ = read_json(self.backend, key)
            if payload is None:
                continue
            try:
                out.append(TaskRecord.model_validate(payload))
            except Exception:
                continue
        return out

    def mark_interrupted(self) -> list[str]:
        """进程启动时调用：把“跑了一半”的任务标记为 interrupted（可继续/放弃）。

        返回被标记的 task_id 列表（供日志与测试断言）。
        """
        marked: list[str] = []
        for record in self.list_all():
            if record.state in INTERRUPTIBLE_STATES:
                record.state = TaskState.INTERRUPTED
                record.progress = {"step": "interrupted", "label": "服务重启，已暂停", "percent": 0}
                record.history.append(
                    {"at": now_iso(), "event": "interrupted_by_restart", "detail": {}}
                )
                self.save(record)
                marked.append(record.task_id)
        return marked
