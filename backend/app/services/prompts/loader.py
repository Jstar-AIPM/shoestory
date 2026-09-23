"""Prompt 模板加载：集中管理，**缺文件时大声报错，绝不静默降级**。

## 为什么要有这个模块（2026-09-21 线上事故复盘）

阶段 4 首次上线时，`backend/.vefaasignore` 里误写了一行 `*.md`，把
`app/services/prompts/resolve_model.md`、`verify_lineart.md` 一起排除出了代码包。
而当时的 `_load_prompt()` 在文件缺失时**静默**返回一句极简提示词：
模型拿不到"字段规范"，输出的 JSON 形状就不对 → `LLM_OUTPUT_INVALID`
→ 线上表现为「点了生成没反应」，而日志里看不到"提示词丢了"这件事。

结论：**Prompt 是运行时必需资源，不是可选项**；缺失必须能被日志和健康检查看见。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import PROMPTS_DIR
from app.core.logging import log_event

logger = logging.getLogger("app.prompts")

#: 运行时会被读取的 Prompt 文件（健康检查与打包自检据此判断代码包是否完整）
REQUIRED_PROMPTS: tuple[str, ...] = (
    "resolve_model.md",
    "verify_lineart.md",
    "rank_source_images.md",
    "screen_source_images.md",
    "inspect_photo.md",
)

#: 已被读取且当时缺失的 Prompt（用于健康检查如实上报）
_MISSING: set[str] = set()


def prompt_path(name: str) -> Path:
    return PROMPTS_DIR / name


def load_prompt_text(name: str, fallback: str = "") -> str:
    """读取 Prompt 模板。

    - 正常：返回文件内容；
    - 缺失或为空：记一条 ERROR 日志（含期望路径），返回 fallback，并记入缺失清单。
    """
    path = prompt_path(name)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _MISSING.add(name)
        log_event(
            logger,
            "prompt_unavailable",
            prompt=name,
            path=str(path),
            reason=exc.__class__.__name__,
            impact="模型拿不到字段规范，输出会走兜底提示词",
        )
        logger.error("Prompt 文件读不到：%s（部署包可能漏了 prompts/ 目录）", path)
        return fallback
    if not text.strip():
        _MISSING.add(name)
        log_event(logger, "prompt_unavailable", prompt=name, path=str(path), reason="empty")
        logger.error("Prompt 文件为空：%s", path)
        return fallback
    _MISSING.discard(name)
    return text


def missing_prompts() -> list[str]:
    """已被读取但当时缺失的 Prompt 名称（升序）。"""
    return sorted(_MISSING)


def reset_missing() -> None:
    """清空缺失清单（仅供测试与自检使用）。"""
    _MISSING.clear()


def prompt_inventory() -> dict[str, bool]:
    """按磁盘现状盘点必需 Prompt 是否就位（不依赖是否已被读取过）。"""
    return {name: prompt_path(name).is_file() for name in REQUIRED_PROMPTS}


def prompts_ready() -> bool:
    return all(prompt_inventory().values())
