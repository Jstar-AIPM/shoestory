"""资产存储：中间产物（原图/抠图/标准画布/画稿候选）与归档画稿。

key 布局（阶段 1 强制项，支持后续按 owner 隔离）：
  owners/{owner_id}/tasks/{task_id}/source_0.jpg      任务源图
  owners/{owner_id}/tasks/{task_id}/cutout.png        去背景结果
  owners/{owner_id}/tasks/{task_id}/canvas_3x2.png    3:2 标准画布
  owners/{owner_id}/tasks/{task_id}/artwork_a{n}.png  第 n 次生成的画稿（历史保留）
  owners/{owner_id}/assets/{shoe_id}/artwork.png      归档后的最终画稿
"""

from __future__ import annotations

from app.core.paths import owner_key
from app.services.storage.backend import StorageBackend


def staging_dir(owner_id: str, task_id: str) -> str:
    return owner_key(owner_id, "tasks", task_id)


def asset_dir(owner_id: str, shoe_id: str) -> str:
    return owner_key(owner_id, "assets", shoe_id)


class AssetStore:
    def __init__(self, backend: StorageBackend) -> None:
        self.backend = backend

    # ---------------- 基础 ----------------
    def put(self, key: str, data: bytes) -> str:
        self.backend.put_bytes(key, data)
        return key

    def get(self, key: str) -> bytes:
        return self.backend.get_bytes(key)

    def exists(self, key: str) -> bool:
        return self.backend.exists(key)

    def delete_prefix(self, prefix: str) -> int:
        return self.backend.delete_prefix(prefix)

    # ---------------- 任务中间产物 ----------------
    def task_key(self, owner_id: str, task_id: str, name: str) -> str:
        return f"{staging_dir(owner_id, task_id)}/{name}"

    def put_task_file(self, owner_id: str, task_id: str, name: str, data: bytes) -> str:
        return self.put(self.task_key(owner_id, task_id, name), data)

    def get_task_file(self, owner_id: str, task_id: str, name: str) -> bytes:
        return self.get(self.task_key(owner_id, task_id, name))

    def clear_task(self, owner_id: str, task_id: str) -> int:
        return self.delete_prefix(staging_dir(owner_id, task_id))

    # ---------------- 归档画稿 ----------------
    def archive_artwork_key(self, owner_id: str, shoe_id: str, name: str = "artwork.png") -> str:
        return f"{asset_dir(owner_id, shoe_id)}/{name}"

    def put_archive_artwork(
        self, owner_id: str, shoe_id: str, data: bytes, name: str = "artwork.png"
    ) -> str:
        return self.put(self.archive_artwork_key(owner_id, shoe_id, name), data)

    def get_archive_artwork(self, owner_id: str, shoe_id: str, name: str = "artwork.png") -> bytes:
        return self.get(self.archive_artwork_key(owner_id, shoe_id, name))
