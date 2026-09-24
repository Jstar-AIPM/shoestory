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


# ---------------- 原图看不到品牌标识时：禁止编造 Logo（2026-09-23 线上实测修正）----------------
# 背景：AJ36 那个角度拍不到飞人 Logo，模型于是编了个装饰性符号，质检正确地判它"Logo 不对"→ 整单失败。
# 结论：logo_fill 与 avoid_logo 必须二选一 —— 看得见才要求填，看不见就明确禁止编造。


def test_avoid_logo_forbids_inventing_a_brand_mark() -> None:
    suffix = _draw_hints_suffix(None, None, avoid_logo=True)
    assert "不要" in suffix and "Logo" in suffix
    assert "不要凭空添加" in suffix or "凭空" in suffix
    assert "装饰" in suffix, "要明确禁止用装饰图形代替品牌标识"


def test_logo_fill_says_only_draw_what_is_visible() -> None:
    suffix = _draw_hints_suffix("耐克勾形（鞋身两侧）", None)
    assert "只画原图里确实能看到的那一处" in suffix or "不得添加原图里没有的品牌标识" in suffix


def test_nothing_visible_and_no_flag_keeps_suffix_silent() -> None:
    """没给 Logo 信息、也没要求避免编造时，不要凭空加一段劝导（保持提示词稳定）。"""
    assert _draw_hints_suffix(None, None) == ""


# --------------------------------------------------------------------------- 2026-09-24 新增


def test_same_color_mark_must_still_be_filled() -> None:
    """同色系的标也要填 —— 这是线上 AF1 浅棕 / 黑色 ASICS 出问题的地方。

    模型是按"照片里的颜色对比"决定要不要填的，浅棕鞋配浅棕勾、黑鞋配黑标时它就不填。
    所以提示词里必须把\"同色也要填\"说死。
    """
    suffix = _draw_hints_suffix("耐克勾形（鞋身外侧）", None)
    assert "同色" in suffix
    assert "照样填成纯黑实心" in suffix


def test_partial_logo_is_not_completed() -> None:
    """Melo 5.5：照片里飞人只露一部分，模型却补成了一个完整的飞人。"""
    suffix = _draw_hints_suffix("飞人（后跟侧面）", None, partial_logo=True)
    assert "只画看得见的那部分" in suffix
    assert "不要把它补全" in suffix


def test_partial_hint_absent_for_fully_visible_logo() -> None:
    suffix = _draw_hints_suffix("飞人", None, partial_logo=False)
    assert "不要把它补全" not in suffix


def test_avoid_logo_wins_when_no_mark_visible() -> None:
    """AJ36：那个角度看不到，就明确禁止编造。"""
    suffix = _draw_hints_suffix(None, None, avoid_logo=True)
    assert "不要编造 Logo" in suffix
    assert "Logo 必须填实" not in suffix


def test_emphasis_sentences_are_reason_specific() -> None:
    """定向重画：不同失败原因补不同的话，不能一律重跑同一套提示词。"""
    from app.services.providers.ark_image import EMPHASIS

    assert "一块实色都没有" in EMPHASIS["underfilled"]
    assert "外轮廓" in EMPHASIS["silhouette"]
