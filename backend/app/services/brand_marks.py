"""品牌标志知识表 + 「填不填、填什么」的确定性决策。

## 这个模块解决什么问题

产品反馈里两类问题都指向同一件事 —— **"该不该填实"这个决定权在模型手里**：

1. **该填的没填**：AF1 的勾是空心的、黑色 ASICS 的虎爪纹没填。
   根因：模型按"照片里的颜色对比"判断要不要填，而浅棕 AF1 / 黑鞋配黑标这类
   同色系配色，它看不出那是个"标记"。实测证据见
   `实验1-截图模式/17-Logo填色检查（黑鞋vs白鞋）`：同款 ASICS 白鞋填了、黑鞋没填。
2. **不该画的画了**：AJ36 那个角度看不到飞人，模型凭空编了一个。
   根因：`avoid_logo` 的判断把"模型认不出"和"照片里看不到"混成了一件事 ——
   于是"认不出"反而触发了"禁止画 Logo"，Stan Smith 就是这么变成纯线稿的。

所以这里做两件事：

- **品牌 → 标志性图形**（`prompts/brand_marks.yaml`）：品牌认得出来就由表决定必须填实；
- **可见程度**（`full` / `partial` / `none`）单独作为一路信号：
  - `none`  → 明确禁止编造（AJ36 的坑）
  - `partial` → 只画看得见的那部分，不许补全（Melo 5.5 的坑）
  - `full`  → 无论颜色是否与鞋身相同，都必须填成实心

决策结果是一个 `FillPlan`，runner 把它翻成提示词里的几句话。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import PROMPTS_DIR

BRAND_MARKS_FILE = "brand_marks.yaml"

#: 可见程度（与 `prompts/inspect_photo.md` 的约定一致）
VISIBILITY_FULL = "full"
VISIBILITY_PARTIAL = "partial"
VISIBILITY_NONE = "none"


@dataclass(frozen=True)
class BrandMark:
    """一个品牌的标志性图形。"""

    brand: str
    mark: str
    position: str = ""
    aliases: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        """品牌串能不能归到这个品牌。支持 Jordan 匹配 Air Jordan 这种包含关系。"""
        names = {_normalize(self.brand), *( _normalize(a) for a in self.aliases )}
        # 两个字的缩写（如 "nb"）容易误匹配，要求长度 >= 3 才能用包含判断
        return any(name == text or (len(name) >= 3 and (name in text or text in name)) for name in names)


@dataclass(frozen=True)
class FillPlan:
    """「填什么、要不要填、能不能编」的最终结论。"""

    #: 写进生成提示词的形状描述（形状 + 位置）；空串表示没有可填的标记
    logo_hint: str = ""
    #: 是否要求填成实心黑块
    must_fill: bool = False
    #: 是否明确禁止添加原图里没有的品牌标识
    forbid_logo: bool = False
    #: 原图只露出一部分 —— 只画看得见的那部分，不要补全
    partial: bool = False
    #: 结论来自哪里（"knowledge" / "vision" / "none"），便于线上排查
    source: str = "none"

    @property
    def has_mark(self) -> bool:
        return bool(self.logo_hint)


def _normalize(value: str) -> str:
    """全角转半角 + 小写 + 去空白，让"ＮＩＫＥ"和"nike"能对上。"""
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    return " ".join(text.split())


def load_brand_marks(path: Path | None = None) -> tuple[BrandMark, ...]:
    """读知识表。文件缺失/损坏时返回空表（**不抛异常** —— 少了它只是退回原来的行为）。"""
    target = path or (PROMPTS_DIR / BRAND_MARKS_FILE)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    out: list[BrandMark] = []
    for brand, spec in (raw.get("brands") or {}).items():
        if not isinstance(spec, dict):
            continue
        mark = str(spec.get("mark") or "").strip()
        if not mark:
            continue
        out.append(
            BrandMark(
                brand=str(brand),
                mark=mark,
                position=str(spec.get("position") or "").strip(),
                aliases=tuple(str(a) for a in (spec.get("aliases") or [])),
            )
        )
    return tuple(out)


def lookup_brand_mark(brand: str, marks: tuple[BrandMark, ...] | None = None) -> BrandMark | None:
    """按品牌串找标志性图形。"""
    text = _normalize(brand)
    if not text:
        return None
    for item in marks if marks is not None else load_brand_marks():
        if item.matches(text):
            return item
    return None


def resolve_fill_plan(
    *,
    brand: str = "",
    model_name: str = "",
    logo_type: str = "",
    logo_position: str = "",
    logo_visibility: str = "",
    logo_fill_required: bool | None = None,
) -> FillPlan:
    """决定"填什么、要不要填、能不能编"。

    判断顺序（每一档都写清理由，改的时候别把顺序弄乱）：

    1. **可见程度 = none** → 禁止编造。这是 AJ36 那次的坑：照片角度看不到，硬要求填
       就会让模型凭空画一个。此时不论品牌知不知道，都不要求填。
    2. **可见程度 = full / partial** → 要填。**形状描述以视觉模型为准，知识表只做兜底**。
       为什么不让知识表优先（实测踩过）：AJ36 那个角度看到的是后跟的 ∞，而知识表写的是
       "Jordan → 飞人" —— 照表走就会让模型画一个照片里不存在的飞人，恰好是我们要修的 bug。
       知识表的价值在于**模型说不出形状的时候**（黑鞋配黑标、白鞋配白标这类同色系，
       模型常不把那个图形当成"标记"），此时由它补上准确的名称。
    3. 可见程度缺失（老任务记录）→ 退回原来的启发式：有 logo_type 就要求填，
       否则禁止编造（但不再因为 `fill_required=False` 就禁止 —— 那是 Stan Smith 的坑）。
    """
    visibility = _normalize(logo_visibility)
    mark = lookup_brand_mark(brand)
    vision_hint = logo_type.strip()
    position = logo_position.strip()

    if visibility == VISIBILITY_NONE:
        return FillPlan(forbid_logo=True, source="vision")

    if visibility in (VISIBILITY_FULL, VISIBILITY_PARTIAL):
        if vision_hint:
            hint, place, source = vision_hint, position, "vision"
        elif mark is not None:
            hint, place, source = mark.mark, position or mark.position, "knowledge"
        else:
            # 看得见一个标记，但既不知道品牌也说不出形状 —— 交给模型自己判断，
            # 不强制也不禁止（禁止会像 Stan Smith 那样把整双鞋变成纯线稿）
            return FillPlan(source="none")
        return FillPlan(
            logo_hint=f"{hint}（{place}）" if place else hint,
            must_fill=True,
            partial=visibility == VISIBILITY_PARTIAL,
            source=source,
        )

    # ---- 可见程度缺失：老记录/老客户端 ----
    # 这一档**刻意保守**：分辨不出"照片里看不到"与"模型没认出来"，宁可禁止编造。
    # 理由：编造出一个错的品牌标是更严重的错（AJ36 那次就是：凭空画了一个装饰符号，
    # 质检判错 → 整单失败、白烧两次生成），而"该填没填"最多是风格偏轻。
    # 新客户端一律会传 visibility，所以品牌知识表在 full/partial 那一档起作用。
    if vision_hint:
        return FillPlan(
            logo_hint=f"{vision_hint}（{position}）" if position else vision_hint,
            must_fill=True,
            source="vision",
        )
    return FillPlan(forbid_logo=True, source="none")
