"""系统接口：健康检查、风格列表（脱敏，不含任何密钥）。"""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container, get_settings
from app.services.datetext import human_hint, parse_date_text
from app.services.prompts.loader import missing_prompts, prompt_inventory

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request, settings=Depends(get_settings)) -> dict:
    container = get_container(request)
    # 部署包完整性：Prompt 文件缺失会让模型走兜底提示词（线上事故 2026-09-21），必须如实上报
    inventory = prompt_inventory()
    absent = sorted(name for name, ok in inventory.items() if not ok)
    degraded = bool(absent)
    key_state = "ok" if settings.ark_key_present else "missing_key"
    if settings.ark_key_present and settings.missing_ark_config:
        key_state = "partial"
    search_state = "ok" if container.providers.search.mode == "real" else (
        "mock" if not settings.search_credentials_present else "ok"
    )
    return {
        "status": "degraded" if degraded else "ok",
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
        "missing_prompts": absent,
        "prompts_read_failed": missing_prompts(),
        "notes": container.notes,
        "runtime": sys.version.split()[0],
    }


@router.get("/emphasis-options")
def list_emphasis_options() -> list[dict[str, str]]:
    """「重新画」时可选的修正方向（产品反馈 10）。

    来源是 `prompts/emphasis.yaml` 里 manual=true 的条目 —— **单一事实来源**：
    界面上的按钮文案与注入提示词的强化句是同一条记录，不会各写一份后对不上。
    """
    from app.services.emphasis import manual_options

    return manual_options()


@router.get("/styles")
def list_styles(request: Request) -> list[dict]:
    return get_container(request).styles.summaries()


@router.get("/date-parse")
def date_parse(text: str = "") -> dict:
    """给界面用：把“自由文本日期”翻译成人话反馈。

    解析规则的唯一真相在服务端（services/datetext.py），前端不重复实现。
    `date_sort_key` 仍然返回（排序要用），但**界面上不再展示** ——
    产品反馈：背后的排序逻辑不需要外显，只显示年份/日期本身即可。
    """
    result = parse_date_text(text)
    return {
        "input": text,
        "date_sort_key": result.key,
        "kind": result.kind,
        "failed": result.failed,
        "hint": human_hint(result),
    }
