"""工具：鞋柜查询 / 编辑 / 删除（query_archive / update_shoe / delete_shoe）。"""

from __future__ import annotations

from app.core.errors import AppError, ErrorCode
from app.schemas.archive import ArchiveItem
from app.services.datetext import parse_date_text
from app.services.storage.archive_store import ArchiveStore
from app.services.storage.asset_store import AssetStore
from app.services.storage.asset_store import asset_dir


def query_archive(
    store: ArchiveStore, owner_id: str, *, sort: str = "date", limit: int = 50, offset: int = 0
) -> tuple[list[ArchiveItem], int, bool]:
    items, corrupted = store.list_sorted(owner_id, sort=sort)
    total = len(items)
    page = items[max(0, offset) : max(0, offset) + max(1, limit)]
    return page, total, corrupted


def update_shoe(
    store: ArchiveStore,
    owner_id: str,
    shoe_id: str,
    *,
    model_name: str | None = None,
    date_text: str | None = None,
    story: str | None = None,
) -> ArchiveItem:
    patch: dict = {}
    if model_name is not None:
        patch["model_name"] = model_name.strip()
    if date_text is not None:
        cleaned = date_text.strip()
        patch["date_text"] = cleaned or None
        patch["date_sort_key"] = parse_date_text(cleaned).key
    if story is not None:
        cleaned_story = story.strip()
        patch["story"] = cleaned_story or None
    if not patch:
        raise AppError(ErrorCode.INVALID_INPUT)
    return store.update(owner_id, shoe_id, patch)


def delete_shoe(
    store: ArchiveStore, asset_store: AssetStore, owner_id: str, shoe_id: str
) -> tuple[ArchiveItem, int]:
    """删除档案并清理其资产目录（返回 (被删条目, 清理文件数)）。"""
    item = store.delete(owner_id, shoe_id)
    removed = 0
    try:
        removed = asset_store.delete_prefix(asset_dir(owner_id, shoe_id))
    except Exception:  # pragma: no cover - 资产清理失败不应阻断删除
        removed = 0
    return item, removed
