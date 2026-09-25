"""鞋柜接口：列表 / 详情 / 编辑 / 删除 / 画稿文件（全部按 owner 过滤）。"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import current_identity, get_container
from app.core.errors import AppError, ErrorCode
from app.schemas.archive import (
    ArchiveItemOut,
    ArchiveListOut,
    ArchiveListResponse,
    ArchivePatchIn,
    DeleteOut,
)
from app.services.tools.query_archive import delete_shoe, query_archive, update_shoe

router = APIRouter(prefix="/archive", tags=["archive"])


def _to_list_item(item) -> ArchiveListOut:
    return ArchiveListOut(
        shoe_id=item.shoe_id,
        model_name=item.model_name,
        artwork_url=f"/api/v1/archive/{item.shoe_id}/artwork.png",
        style_id=item.style_id,
        date_text=item.date_text,
        date_sort_key=item.date_sort_key,
        created_at=item.created_at,
        has_story=bool(item.story),
    )


def _to_detail(item, *, position: int | None = None, total: int | None = None,
               prev_shoe_id: str | None = None, next_shoe_id: str | None = None) -> ArchiveItemOut:
    return ArchiveItemOut(
        shoe_id=item.shoe_id,
        model_name=item.model_name,
        model_name_input=item.model_name_input,
        artwork_url=f"/api/v1/archive/{item.shoe_id}/artwork.png",
        artwork_meta=item.artwork_meta.model_dump(),
        date_text=item.date_text,
        date_sort_key=item.date_sort_key,
        story=item.story,
        created_at=item.created_at,
        style_id=item.style_id,
        style_version=item.style_version,
        source=item.source.model_dump(),
        quality=item.quality.model_dump(),
        rights_note=item.rights_note,
        position=position,
        total=total,
        prev_shoe_id=prev_shoe_id,
        next_shoe_id=next_shoe_id,
    )


@router.get("", response_model=ArchiveListResponse)
def list_archive(
    request: Request,
    owner_id: str = Depends(current_identity),
    sort: str = Query(default="date", pattern="^(date|created)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ArchiveListResponse:
    container = get_container(request)
    items, total, corrupted = query_archive(
        container.archive_store, owner_id, sort=sort, limit=limit, offset=offset
    )
    return ArchiveListResponse(
        total=total,
        items=[_to_list_item(item) for item in items],
        warning=(
            "本地档案文件损坏，已备份原文件并以空档案继续，请把这件事告诉 AI。"
            if corrupted
            else None
        ),
    )


@router.get("/{shoe_id}", response_model=ArchiveItemOut)
def get_archive(
    shoe_id: str,
    request: Request,
    owner_id: str = Depends(current_identity),
    sort: str = Query(default="date", pattern="^(date|created)$"),
) -> ArchiveItemOut:
    """详情。带上 `sort` 时额外返回上一双/下一双，供详情页直接翻页。"""
    container = get_container(request)
    item = container.archive_store.get(owner_id, shoe_id)
    ordered, _corrupted = container.archive_store.list_sorted(owner_id, sort=sort)
    ids = [entry.shoe_id for entry in ordered]
    if shoe_id not in ids:  # 理论上不会发生，兜底
        return _to_detail(item)
    index = ids.index(shoe_id)
    return _to_detail(
        item,
        position=index + 1,
        total=len(ids),
        prev_shoe_id=ids[index - 1] if index > 0 else None,
        next_shoe_id=ids[index + 1] if index + 1 < len(ids) else None,
    )


@router.patch("/{shoe_id}", response_model=ArchiveItemOut)
def patch_archive(
    shoe_id: str,
    payload: ArchivePatchIn,
    request: Request,
    owner_id: str = Depends(current_identity),
) -> ArchiveItemOut:
    container = get_container(request)
    item = update_shoe(
        container.archive_store,
        owner_id,
        shoe_id,
        model_name=payload.model_name,
        date_text=payload.date_text,
        story=payload.story,
    )
    return _to_detail(item)


@router.delete("/{shoe_id}", response_model=DeleteOut)
def remove_archive(
    shoe_id: str,
    request: Request,
    owner_id: str = Depends(current_identity),
    confirm: bool = Query(default=False),
) -> DeleteOut:
    if not confirm:
        raise AppError(ErrorCode.CONFIRM_REQUIRED)
    container = get_container(request)
    _item, removed = delete_shoe(container.archive_store, container.asset_store, owner_id, shoe_id)
    return DeleteOut(deleted=True, removed_files=removed)


@router.get("/{shoe_id}/artwork.png")
def get_archive_artwork(
    shoe_id: str, request: Request, owner_id: str = Depends(current_identity)
) -> Response:
    container = get_container(request)
    item = container.archive_store.get(owner_id, shoe_id)
    try:
        data = container.asset_store.get(item.artwork_path)
    except Exception as exc:
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND) from exc
    etag = hashlib.sha1(data).hexdigest()[:16]
    return Response(
        content=data,
        media_type="image/png",
        headers={"ETag": f'"{etag}"', "Cache-Control": "private, max-age=60"},
    )
