"""鞋柜档案存储：`owners/{owner_id}/archive.json`。

- schema_version 版本校验（过新 -> SCHEMA_TOO_NEW，拒绝写入）
- 原子写入 + 损坏备份（损坏时返回 warning，仍可读）
- 单写者锁（进程内；部署时限单实例 —— 多实例并发会互相覆盖 JSON）
- 排序：manual_order 非空优先 -> date_sort_key 升序（null 最后）-> created_at
"""

from __future__ import annotations

import threading

from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.core.paths import owner_key
from app.schemas.archive import ArchiveFile, ArchiveItem
from app.services.storage.atomic_io import read_json, write_json
from app.services.storage.backend import StorageBackend

SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA = 1

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.RLock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.RLock()
        return _locks[key]


def archive_key(owner_id: str) -> str:
    return owner_key(owner_id, "archive.json")


def sort_items(items: list[ArchiveItem], sort: str = "date") -> list[ArchiveItem]:
    """阶段 1：默认按日期由旧到新（成长时间线感）。

    - manual_order 非空项排在最前（阶段 1 无此数据，字段已预留）
    - date_sort_key 升序，null 排最后（其内部按 created_at 升序）
    - sort="created" 时按 created_at 升序（阶段 2 才会从界面切换）
    """

    def key(item: ArchiveItem):
        pinned = item.manual_order
        if pinned is not None:
            return (0, pinned, 0, "", item.created_at, item.shoe_id)
        if sort == "created":
            return (1, 0, 0, item.created_at, "", item.shoe_id)
        return (
            1,
            0,
            1 if item.date_sort_key is None else 0,
            item.date_sort_key or "",
            item.created_at,
            item.shoe_id,
        )

    return sorted(items, key=key)


class ArchiveStore:
    def __init__(self, backend: StorageBackend) -> None:
        self.backend = backend

    # ---------------- 读写 ----------------
    def load(self, owner_id: str) -> tuple[list[ArchiveItem], bool]:
        key = archive_key(owner_id)
        payload, corrupted = read_json(self.backend, key)
        if payload is None:
            return [], corrupted
        version = int(payload.get("schema_version", SCHEMA_VERSION))
        if version > MAX_SUPPORTED_SCHEMA:
            raise AppError(
                ErrorCode.SCHEMA_TOO_NEW,
                detail={"found": version, "supported": MAX_SUPPORTED_SCHEMA},
            )
        try:
            file_model = ArchiveFile.model_validate(payload)
        except Exception:
            from app.services.storage.atomic_io import backup_corrupt

            backup_corrupt(self.backend, key)
            return [], True
        return [item for item in file_model.items if item.owner_id == owner_id], False

    def save(self, owner_id: str, items: list[ArchiveItem]) -> None:
        key = archive_key(owner_id)
        payload = ArchiveFile(
            schema_version=SCHEMA_VERSION,
            updated_at=now_iso(),
            items=items,
        )
        write_json(self.backend, key, payload)

    # ---------------- 业务操作 ----------------
    def add(self, item: ArchiveItem) -> ArchiveItem:
        key = archive_key(item.owner_id)
        with _lock_for(key):
            items, _ = self.load(item.owner_id)
            items.append(item)
            self.save(item.owner_id, items)
        return item

    def get(self, owner_id: str, shoe_id: str) -> ArchiveItem:
        with _lock_for(archive_key(owner_id)):
            items, _ = self.load(owner_id)
        for item in items:
            if item.shoe_id == shoe_id:
                return item
        raise AppError(ErrorCode.ARCHIVE_NOT_FOUND)

    def list_sorted(self, owner_id: str, sort: str = "date") -> tuple[list[ArchiveItem], bool]:
        with _lock_for(archive_key(owner_id)):
            items, corrupted = self.load(owner_id)
        return sort_items(items, sort), corrupted

    def update(self, owner_id: str, shoe_id: str, patch: dict) -> ArchiveItem:
        key = archive_key(owner_id)
        with _lock_for(key):
            items, _ = self.load(owner_id)
            target: ArchiveItem | None = None
            updated: list[ArchiveItem] = []
            for item in items:
                if item.shoe_id == shoe_id:
                    merged = item.model_dump(mode="json")
                    merged.update(patch)
                    target = ArchiveItem.model_validate(merged)
                    updated.append(target)
                else:
                    updated.append(item)
            if target is None:
                raise AppError(ErrorCode.ARCHIVE_NOT_FOUND)
            self.save(owner_id, updated)
        return target

    def delete(self, owner_id: str, shoe_id: str) -> ArchiveItem:
        key = archive_key(owner_id)
        with _lock_for(key):
            items, _ = self.load(owner_id)
            target = next((i for i in items if i.shoe_id == shoe_id), None)
            if target is None:
                raise AppError(ErrorCode.ARCHIVE_NOT_FOUND)
            self.save(owner_id, [i for i in items if i.shoe_id != shoe_id])
        return target
