"""journal / 轨迹：每步写入任务文件 + trace JSONL（PRD 4.10）。

轨迹是未来微调「鞋 -> 线稿」专用模型的原料，因此记录：型号、图源、prompt 版本、
生成参数、质检分数、用户“重新生成/重新输入”的选择与原因。
轨迹按 owner 隔离存放：`owners/{owner_id}/traces/trace_{task_id}.jsonl`。
"""

from __future__ import annotations

from typing import Any

from app.core.idgen import now_iso
from app.core.logging import redact
from app.core.paths import owner_key
from app.schemas.task import TaskRecord
from app.services.storage.atomic_io import append_jsonl
from app.services.storage.backend import StorageBackend


def trace_key(owner_id: str, task_id: str) -> str:
    return owner_key(owner_id, "traces", f"trace_{task_id}.jsonl")


class TraceWriter:
    def __init__(self, backend: StorageBackend, owner_id: str, task_id: str) -> None:
        self.backend = backend
        self.owner_id = owner_id
        self.task_id = task_id
        self.key = trace_key(owner_id, task_id)

    def write(self, event: str, **fields: Any) -> None:
        payload = {"at": now_iso(), "task_id": self.task_id, "event": event}
        for key, value in fields.items():
            if key in {"story", "api_key", "password"}:
                payload[f"{key}_len"] = len(value or "") if key == "story" else "***"
                continue
            payload[key] = redact(value) if isinstance(value, str) else value
        append_jsonl(self.backend, self.key, payload)


def append_history(record: TaskRecord, event: str, detail: dict | None = None) -> None:
    record.history.append({"at": now_iso(), "event": event, "detail": detail or {}})
