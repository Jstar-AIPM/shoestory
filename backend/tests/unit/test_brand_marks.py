"""「填什么、要不要填、能不能编」决策的单元测试（services/brand_marks.py）。

这一层是 2026-09-24 产品反馈的直接产物：**把决定权从模型手里收回到代码**。
每个用例都对应线上真实出现过的一张图，注释里写清楚是哪一张、当时错在哪。
"""

from __future__ import annotations

from app.services.brand_marks import (
    load_brand_marks,
    lookup_brand_mark,
    resolve_fill_plan,
)


def test_knowledge_table_is_loadable_and_non_trivial() -> None:
    marks = load_brand_marks()
    assert len(marks) >= 8, "基础品牌至少要在表里"
    names = {item.brand for item in marks}
    assert {"nike", "jordan", "adidas", "asics", "new balance"} <= names


def test_lookup_matches_brand_and_alias() -> None:
    assert lookup_brand_mark("Nike").mark.startswith("耐克勾形")
    assert lookup_brand_mark("Air Jordan").brand == "jordan"  # 包含关系
    assert lookup_brand_mark("亚瑟士").brand == "asics"  # 别名
    assert lookup_brand_mark("ＡＤＩＤＡＳ").brand == "adidas"  # 全角 + 大小写
    assert lookup_brand_mark("") is None
    assert lookup_brand_mark("某个没听过的牌子") is None


def test_full_visibility_forces_fill_even_when_model_cannot_name_it() -> None:
    """黑色 ASICS / Stan Smith：标与鞋身同色，模型说不出形状，但形状确实看得见。

    模型是按颜色对比决定要不要填的 —— 实测同款 ASICS 白鞋填了、黑鞋没填。
    现在只要 visibility=full，就由知识表强制要求填实。
    """
    plan = resolve_fill_plan(brand="ASICS", logo_visibility="full")
    assert plan.must_fill is True
    assert "虎爪纹" in plan.logo_hint
    assert plan.forbid_logo is False
    assert plan.source == "knowledge"


def test_vision_description_wins_over_knowledge_table() -> None:
    """AJ36：模型看到的是后跟的 ∞，而知识表写的是"Jordan → 飞人"。

    如果照表走，模型就会去画一个照片里根本不存在的飞人 —— 恰好是 2026-09-23
    那次翻车的 bug。所以**以照片为准，知识表只做兜底**。
    """
    plan = resolve_fill_plan(
        brand="Jordan", logo_type="无限符号（∞）", logo_position="后跟侧", logo_visibility="full"
    )
    assert "∞" in plan.logo_hint
    assert "飞人" not in plan.logo_hint
    assert plan.source == "vision"


def test_partial_visibility_never_names_the_mark() -> None:
    """Melo 5.5：照片里那个标只露一半，**刻意不给形状名**。

    实测踩过的坑：体检把它认成“耐克勾形”，我们照说“把耐克勾形填实”，
    模型就画了一个完整的黑色勾 —— 判官判“凭空替换品牌标识”。
    只露一部分时，说出名字反而会诱使它画错形状或补全，所以只描述“可见的那一小块”。
    """
    plan = resolve_fill_plan(
        brand="Jordan", logo_type="飞人", logo_position="后跟侧面", logo_visibility="partial"
    )
    assert plan.must_fill is True
    assert plan.partial is True
    assert plan.logo_hint == "", "只露一部分时不能给出品牌形状名"
    assert plan.source == "partial"


def test_partial_logo_gets_a_dedicated_prompt_block() -> None:
    """提示词里要有专门的一段，且不能出现品牌标准形状的名字。"""
    from app.services.providers.ark_image import _draw_hints_suffix

    suffix = _draw_hints_suffix(None, None, partial_logo=True)
    assert "只画看得见的那一小块标识" in suffix
    assert "不要按任何品牌的标准形状把它补全" in suffix
    assert "填实" in suffix, "只露一部分也要填，只是不按标准形状补全"


def test_invisible_mark_forbids_inventing_one() -> None:
    """AJ36 那个角度看不到飞人：不能要求填，必须明确禁止编造。"""
    plan = resolve_fill_plan(brand="Jordan", logo_type="", logo_visibility="none")
    assert plan.forbid_logo is True
    assert plan.must_fill is False
    assert plan.logo_hint == ""


def test_invisible_mark_stays_forbidden_even_with_known_brand() -> None:
    """知识表认识这个牌子，也不能推翻"照片里看不到"这件事。"""
    plan = resolve_fill_plan(brand="Nike", logo_visibility="none")
    assert plan.forbid_logo is True
    assert plan.logo_hint == ""


def test_unknown_brand_but_visible_mark_is_still_filled() -> None:
    """小牌子 / 认不出品牌，但形状看得见：照模型描述填，不禁止。"""
    plan = resolve_fill_plan(brand="", logo_type="侧边三角标", logo_visibility="full")
    assert plan.must_fill is True
    assert "三角标" in plan.logo_hint
    assert plan.forbid_logo is False


def test_visible_but_unnamable_mark_neither_forces_nor_forbids() -> None:
    """看得见一个标记，但既不知品牌也说不出形状 —— 交给模型自己判断。

    这里刻意**不禁止**：禁止会像 Stan Smith 那样把整双鞋变成纯线稿。
    """
    plan = resolve_fill_plan(brand="", logo_type="", logo_visibility="full")
    assert plan.must_fill is False
    assert plan.forbid_logo is False
    assert plan.logo_hint == ""


def test_legacy_record_without_visibility_keeps_old_conservative_behavior() -> None:
    """老任务记录没有 visibility 字段：分辨不出"看不到"与"没认出来"，宁可禁止编造。"""
    assert resolve_fill_plan(brand="Nike", logo_type="耐克勾形", logo_position="外侧").must_fill
    forbidden = resolve_fill_plan(brand="Nike", logo_type="")
    assert forbidden.forbid_logo is True
    assert forbidden.logo_hint == ""


def test_invalid_visibility_is_treated_as_missing() -> None:
    plan = resolve_fill_plan(brand="Nike", logo_type="", logo_visibility="maybe")
    assert plan.forbid_logo is True


# --------------------------------------------------------------------------- 视角/朝向/完整性（产品反馈 7/11/12）


def test_side_view_and_facing_drive_the_new_decisions() -> None:
    """新增三个字段各自对应一个产品决定，别让它们退化成"永远放行"。"""
    from app.schemas.inspect import PhotoInspectOut

    assert PhotoInspectOut(view="lateral").is_side_view is True
    assert PhotoInspectOut(view="top").is_side_view is False
    assert PhotoInspectOut(view="three_quarter").is_side_view is False
    # 缺字段（老记录 / 模型没给）时放行 —— 不能因为一个新字段缺失就把原来能跑的流程卡死
    assert PhotoInspectOut(view="").is_side_view is True

    # 鞋头朝右 → 生成前翻转，保证鞋柜里统一朝左
    assert PhotoInspectOut(facing="right").needs_mirror is True
    assert PhotoInspectOut(facing="left").needs_mirror is False
    assert PhotoInspectOut(facing="unknown").needs_mirror is False

    # 被切掉鞋头/鞋跟 → 提示重新框选
    assert PhotoInspectOut(complete=False).complete is False


def test_vision_output_normalises_loose_values() -> None:
    """模型偶尔会写中文或同义词，容错一下，别让整条链路因为一个词失配。"""
    from app.schemas.inspect import PhotoInspectOut

    assert PhotoInspectOut(view="侧面").view == "lateral"
    assert PhotoInspectOut(view="俯视").view == "top"
    assert PhotoInspectOut(facing="RIGHT").facing == "right"
    assert PhotoInspectOut(view="胡说").view == ""
