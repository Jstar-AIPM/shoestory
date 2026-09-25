"""管理员接口（邀请码管理）——只对管理员码开放。

产品经理需要的最小运维面：
- 看每个码用了多少次、各自建了几双鞋
- 新建邀请码 / 作废邀请码
- **一键清理某个访客的数据**（演示几个月后避免对象存储里堆垃圾）
- 管理员码不可作废（在 store 层硬保护）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container, require_admin_session
from app.core.errors import AppError, ErrorCode
from app.core.paths import owner_prefix
from app.schemas.auth import CreateCodeIn, CreateCodeOut, CodeListOut, PurgeOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/codes", response_model=CodeListOut)
def list_codes(request: Request, _admin=Depends(require_admin_session)) -> CodeListOut:
    container = get_container(request)
    codes = container.invite_store.list_all()

    items = []
    for record in codes:
        # 该访客建了几双鞋（读一次 archive.json；单用户规模，成本可忽略）
        try:
            archived, _ = container.archive_store.load(record.owner_id)
            archived_count = len(archived)
        except Exception:  # pragma: no cover - 单个 owner 损坏不影响整体列表
            archived_count = -1
        items.append(record.public_dict() | {"archived_count": archived_count})

    return CodeListOut(total=len(items), items=items)


@router.post("/codes", response_model=CreateCodeOut, status_code=201)
def create_code(
    payload: CreateCodeIn, request: Request, _admin=Depends(require_admin_session)
) -> CreateCodeOut:
    container = get_container(request)
    record = container.invite_store.create(
        note=payload.note,
        max_uses=payload.max_uses,
        ttl_days=payload.ttl_days,
    )
    return CreateCodeOut(**record.public_dict())


@router.post("/codes/{code}/revoke", response_model=CreateCodeOut)
def revoke_code(
    code: str, request: Request, _admin=Depends(require_admin_session)
) -> CreateCodeOut:
    container = get_container(request)
    record = container.invite_store.revoke(code)
    return CreateCodeOut(**record.public_dict())


@router.delete("/owners/{owner_id}", response_model=PurgeOut)
def purge_owner(
    owner_id: str, request: Request, _admin=Depends(require_admin_session)
) -> PurgeOut:
    """清理某个访客的全部数据（档案 + 任务 + 资产 + 轨迹）。不可撤销。"""
    container = get_container(request)

    # 防误删：管理员自己的 owner_id 不允许通过这个接口清理
    admin_records = [c for c in container.invite_store.list_all() if c.is_admin()]
    if any(c.owner_id == owner_id for c in admin_records):
        raise AppError(ErrorCode.FORBIDDEN, message="不能清理管理员自己的鞋柜。")

    removed = container.asset_store.delete_prefix(owner_prefix(owner_id))
    return PurgeOut(owner_id=owner_id, removed_files=removed)
