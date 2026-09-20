"""系统接口：健康检查、风格列表（脱敏，不含任何密钥）。"""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container, get_settings
from app.services.datetext import parse_date_text

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request, settings=Depends(get_settings)) -> dict:
    container = get_container(request)
    key_state = "ok" if settings.ark_key_present else "missing_key"
    if settings.ark_key_present and settings.missing_ark_config:
        key_state = "partial"
    search_state = "ok" if container.providers.search.mode == "real" else (
        "mock" if not settings.search_credentials_present else "ok"
    )
    return {
        "status": "ok",
        "version": settings.version,
        "env": settings.env,
        "python": platform.python_version(),
        "storage": settings.storage_provider,
        "providers": {
            "mode": container.providers.mode,
            "ark": key_state,
            "text_model": settings.ark_text_model or None,
            "vision_model": settings.ark_vision_model or None,
            "image_model": settings.ark_image_model or None,
            "search": search_state,
        },
        "flags": {
            "manual_source_enabled": bool(settings.enable_manual_source and settings.env == "dev"),
            "mock_mode": container.providers.mode == "mock",
            "inline_pipeline": settings.pipeline_inline,
        },
        "missing_config": container.providers.missing,
        "notes": container.notes,
        "runtime": sys.version.split()[0],
    }


@router.get("/styles")
def list_styles(request: Request) -> list[dict]:
    return get_container(request).styles.summaries()


@router.get("/date-parse")
def date_parse(text: str = "") -> dict:
    """给验收界面用：实时显示“自由文本日期”被解析成什么排序键。

    解析规则的唯一真相在服务端（services/datetext.py），前端不重复实现。
    """
    result = parse_date_text(text)
    return {
        "input": text,
        "date_sort_key": result.key,
        "kind": result.kind,
        "failed": result.failed,
        "hint": (
            "无法解析，会排在最后"
            if result.failed
            else ("留空即可" if not result.key else f"将按 {result.key} 排序")
        ),
    }
