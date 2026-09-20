"""原子读写与损坏处理（手册 [A]：结构化文件必须有 schema 版本、原子写入、损坏处理）。

- 写：交由后端原子写入（本地后端是 tmp + fsync + os.replace）
- 读：JSON 解析失败 -> 备份为 `{key}.corrupt-{ts}`，返回 (None, True)，由上层返回
  STORAGE_CORRUPT 警告并继续（绝不静默丢数据，也绝不崩服务）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.errors import AppError, ErrorCode
from app.services.storage.backend import KeyNotFound, StorageBackend


def _dumps(payload: Any) -> bytes:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def write_json(backend: StorageBackend, key: str, payload: Any) -> None:
    backend.put_bytes(key, _dumps(payload))


def read_json(backend: StorageBackend, key: str) -> tuple[dict[str, Any] | None, bool]:
    """返回 (payload, corrupted)。文件不存在 -> (None, False)。"""
    try:
        raw = backend.get_bytes(key)
    except KeyNotFound:
        return None, False
    except AppError:
        raise
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        backup_corrupt(backend, key)
        return None, True
    if not isinstance(data, dict):
        backup_corrupt(backend, key)
        return None, True
    return data, False


def backup_corrupt(backend: StorageBackend, key: str) -> str | None:
    """把损坏文件改名保留（便于人工恢复），不删除任何用户数据。"""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    new_key = f"{key}.corrupt-{stamp}"
    try:
        raw = backend.get_bytes(key)
    except Exception:
        return None
    try:
        backend.put_bytes(new_key, raw)
        backend.delete(key)
        return new_key
    except Exception:  # pragma: no cover - 备份失败不影响启动
        return None


def append_jsonl(backend: StorageBackend, key: str, payload: dict[str, Any]) -> None:
    """轨迹文件追加（低频，整文件原子重写即可）。"""
    existing = b""
    try:
        existing = backend.get_bytes(key)
    except KeyNotFound:
        existing = b""
    line = (json.dumps(payload, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    backend.put_bytes(key, existing + line)


def read_jsonl(backend: StorageBackend, key: str) -> list[dict[str, Any]]:
    try:
        raw = backend.get_bytes(key)
    except KeyNotFound:
        return []
    out: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
