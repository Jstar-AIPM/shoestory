"""生图提示词注入（Logo 填色 + 鞋身文字 + 填色边界）的单元测试。

对应决策记录「V2 输入与风格」第三、七节：
- Logo 标志性图形必须填实（硬性）；
- 鞋身文字尽力还原，但「宁缺勿错」；
- 填色边界：只许填实小元素（Logo/鞋眼孔/透气孔），鞋带/中底/鞋面必须用轮廓线。
"""

from __future__ import annotations

from app.services.providers.ark_image import _draw_hints_suffix


def test_empty_hints_yield_empty_suffix() -> None:
    assert _draw_hints_suffix(None, None) == ""
    assert _draw_hints_suffix("", []) == ""
    assert _draw_hints_suffix(None, []) == ""


def test_logo_and_texts_both_injected() -> None:
    suffix = _draw_hints_suffix("两侧交叉条纹（鞋身两侧）", ["GEL"])

    assert "两侧交叉条纹" in suffix
    assert "鞋身两侧" in suffix
    assert "GEL" in suffix
    # Logo 填色是硬性要求
    assert "纯黑实心块" in suffix
    # 文字「宁缺勿错」
    assert "宁" in suffix and "省略" in suffix


def test_fill_boundary_always_rides_along() -> None:
    """只要给了 Logo 或文字，就必须带上「填色边界」约束（鞋带不得实心）。"""
    suffix = _draw_hints_suffix("耐克勾形", None)
    assert "鞋带" in suffix
    assert "中底" in suffix
    assert "鞋面" in suffix
    assert "不得填成实心块" in suffix


def test_texts_only_does_not_claim_logo() -> None:
    suffix = _draw_hints_suffix(None, ["AIR", "ZOOM"])
    assert "AIR" in suffix and "ZOOM" in suffix
    assert "Logo 填色" not in suffix
