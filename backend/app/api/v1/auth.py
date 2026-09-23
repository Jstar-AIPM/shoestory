"""鉴权接口：邀请码登录 / 查看当前身份 / 退出。

产品规则（阶段 4，与内部工程笔记 4.7(2) 一致）：
- 登录本身**不消耗**生成额度（额度只在生成时扣）；
- 一个邀请码 = 一个鞋柜（同码换设备登录仍回到自己的鞋柜）；
- 额度用完 / 码过期后：**已归档的鞋柜仍可查看**，只是不能再生成。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_session, get_container, require_admin_session
from app.core.config import Settings
from app.schemas.auth import LoginIn, LoginOut, MeOut
from app.services.auth.session import COOKIE_NAME

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, value: str, max_age_seconds: int, secure: bool) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=value,
        max_age=max_age_seconds,
        httponly=True,  # JS 读不到，降低 XSS 风险
        samesite="lax",
        secure=secure,  # HTTPS 下才回传
        path="/",
    )


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, response: Response) -> LoginOut:
    container = get_container(request)
    settings: Settings = container.settings

    record = container.invite_store.authenticate(payload.code)
    session = container.session_signer.issue(record.owner_id, record.role)
    value = container.session_signer.sign_value(session)
    _set_session_cookie(response, value, settings.session_ttl_days * 24 * 3600, secure=settings.env == "prod")

    return LoginOut(
        owner_id=record.owner_id,
        role=record.role,
        expires_at=session.expires_at,
        code_expires_at=record.expires_at,
        remaining=record.remaining,
        message="已进入您的鞋柜" if record.role != "admin" else "已进入管理员模式",
    )


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "message": "已退出"}


@router.get("/me", response_model=MeOut)
def me(request: Request) -> MeOut:
    container = get_container(request)
    settings: Settings = container.settings

    if not settings.auth_required:
        # 本地开发：返回固定身份，标清"未启用登录"，避免前端误以为已登录
        return MeOut(
            authenticated=True,
            owner_id=settings.dev_owner_id,
            role="admin",
            auth_required=False,
            remaining=None,
            can_generate=True,
            code_expires_at=None,
            message="本地开发模式（未启用邀请码登录）",
        )

    session = current_session(request)
    if session is None:
        return MeOut(
            authenticated=False,
            owner_id=None,
            role=None,
            auth_required=True,
            remaining=None,
            can_generate=False,
            code_expires_at=None,
            message="请先用邀请码进入",
        )

    record = container.invite_store.find_by_owner(session.owner_id)
    if record is None:
        return MeOut(
            authenticated=False,
            owner_id=None,
            role=None,
            auth_required=True,
            remaining=None,
            can_generate=False,
            code_expires_at=None,
            message="请先用邀请码进入",
        )

    can_generate = record.is_admin() or (record.status == "active" and not record.expired() and not record.exhausted())
    return MeOut(
        authenticated=True,
        owner_id=session.owner_id,
        role=session.role,
        auth_required=True,
        remaining=record.remaining,
        can_generate=can_generate,
        code_expires_at=record.expires_at,
        message=(
            "管理员模式（不限次数）"
            if record.is_admin()
            else ("可以查看鞋柜，但生成次数已用完" if not can_generate else f"还可生成 {record.remaining} 次")
        ),
    )
