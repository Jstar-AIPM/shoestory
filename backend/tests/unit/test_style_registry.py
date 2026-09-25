"""风格注册表：隐藏语义、默认选型、以及"隐藏≠禁用"。

## 背景（2026-09-24）

主风格切成水彩之后，黑白线稿被设为 `hidden: true` —— **不对外提供**（不出现在风格列表、
界面上选不到），但**代码与文件全部保留**，因为：
- 老档案还要按它渲染；
- 它身上那些与风格无关的修复（抠图补白鞋、骨架图补外轮廓、选稿优先取通过的）水彩也在用；
- 后续会把"填色可控性"再做一轮，做完改回一个字段就能重新启用。

所以"隐藏"必须有精确的含义。我第一版把"默认风格也强制不能落到隐藏风格上"写进去了，
结果是**测试夹具明明指定了黑白风格却被悄悄换成了水彩** —— 静默改写别人的配置是坏设计，
这组测试就是钉住这个教训。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import STYLES_DIR
from app.core.errors import AppError
from app.services.style.registry import StyleRegistry


@pytest.fixture
def registry() -> StyleRegistry:
    return StyleRegistry(Path(STYLES_DIR))


def test_watercolor_is_the_public_style(registry: StyleRegistry) -> None:
    assert registry.available_ids() == ["watercolor"]


def test_hidden_style_is_not_listed(registry: StyleRegistry) -> None:
    listed = [item["style_id"] for item in registry.summaries()]
    assert "bw_lineart" not in listed, "隐藏的风格不该出现在对用户的列表里"
    assert "watercolor" in listed


def test_hidden_style_is_still_loadable(registry: StyleRegistry) -> None:
    """隐藏 ≠ 删除：老档案还要按它渲染，所以必须还能取到。"""
    style = registry.get("bw_lineart")
    assert style.hidden is True
    assert style.binarize is True


def test_explicit_hidden_style_is_honoured(registry: StyleRegistry) -> None:
    """显式指定（请求里带了、或配置里写了）就照办，哪怕它已隐藏。

    这是被实测纠正过的一条：第一版写成了"默认也不许落到隐藏风格"，
    结果测试夹具指定了黑白风格却被静默换成水彩。
    """
    assert registry.resolve_for_new_task("bw_lineart", "watercolor").style_id == "bw_lineart"


def test_configured_default_is_honoured_even_if_hidden(registry: StyleRegistry) -> None:
    """没显式给 style_id 时按配置的默认来 —— **默认即使是隐藏风格也照用**。"""
    assert registry.resolve_for_new_task(None, "bw_lineart").style_id == "bw_lineart"


def test_unknown_explicit_style_raises(registry: StyleRegistry) -> None:
    """请求里显式给了不存在的风格 → 报错，不能悄悄换一个。"""
    with pytest.raises(AppError):
        registry.resolve_for_new_task("no_such_style", "watercolor")


def test_unknown_default_falls_back_to_public_style(registry: StyleRegistry) -> None:
    """只有默认 id 根本不存在时才兜底 —— 防"环境变量拼错一个字母 → 点生成没反应"。"""
    assert registry.resolve_for_new_task(None, "typo_style").style_id == "watercolor"
    assert registry.resolve_for_new_task("", "").style_id == "watercolor"


def test_public_style_is_watercolor_not_binary(registry: StyleRegistry) -> None:
    """当前唯一对外的风格就是水彩，且它绝不能走二值化。"""
    style = registry.resolve_for_new_task(None, "")
    assert style.style_id == "watercolor"
    assert style.binarize is False
    assert style.judge_prompt == "verify_watercolor.md"
