"""上传图体检的输出结构（对应 prompts/inspect_photo.md）。

一次视觉调用同时得到：是否鞋 · 鞋的数量 · 品牌/型号 · Logo 形状与位置 · 鞋身文字清单。
下游用途：
  ① 三档判定（明确是鞋 → 通过 / 明确不是鞋 → 友好拒绝 / 不确定 → 放行 + 软提示）
  ② 注入生图提示词（Logo 填色要求 + 要呈现的文字）
  ③ 归档标题自动命名（品牌 + 型号）
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: ``is_shoe`` 低于此置信度时，我们**不拒绝**，而是放行并给软提示。
#: 理由：拒绝太严比选错更伤体验（V1 的教训）。
UNCERTAIN_CONFIDENCE = 0.45


class LogoInfo(BaseModel):
    """品牌标志性图形（线稿里需要填实的那部分）。

    ``visibility`` 描述"这张照片里看不看得见形状"，与颜色对比无关 ——
    黑色鞋上的黑色 Logo 也算看得见。它是"该不该填实 / 要不要禁止编造"的决策依据，
    与 ``type``（说不出形状时留空）是两码事：见 services/brand_marks.py。
    """

    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="", max_length=60)
    position: str = Field(default="", max_length=60)
    #: full / partial / none；空串 = 老记录没有这个字段
    visibility: str = Field(default="", max_length=10)
    fill_required: bool = True
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("type", "position", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("visibility", mode="before")
    @classmethod
    def _clean_visibility(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip().lower()
        return text if text in {"full", "partial", "none"} else ""

    @property
    def usable(self) -> bool:
        """够不够具体到可以写进提示词（含糊的"图案"没用）。"""
        return len(self.type) >= 2

    @property
    def visible(self) -> bool:
        """形状能不能辨认（老记录缺这个字段时，用类型是否能说出来当退路）。"""
        if self.visibility:
            return self.visibility != "none"
        return self.usable


class ShoeText(BaseModel):
    """鞋身上可辨认的文字。

    ``box`` 是文字在体检图里的**归一化边界框** ``[x, y, w, h]``（均 ∈ [0,1]，相对整图）。
    它用于「文字兜底贴合」：当模型把文字画糊/画错时，从原图裁出这块区域、二值化后贴到线稿。
    """

    model_config = ConfigDict(extra="ignore")

    text: str = Field(default="", max_length=40)
    position: str = Field(default="", max_length=60)
    box: tuple[float, float, float, float] | None = None

    @field_validator("text", "position", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("box", mode="before")
    @classmethod
    def _clean_box(cls, value: Any) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            x, y, w, h = (float(v) for v in value)
        except (TypeError, ValueError):
            return None
        # 归一化边界框：夹到 [0,1] 内，宽高至少 0.01（过小/非法一律视为无框）
        if w <= 0.01 or h <= 0.01:
            return None
        return (
            max(0.0, min(1.0, x)),
            max(0.0, min(1.0, y)),
            min(1.0, max(0.0, w)),
            min(1.0, max(0.0, h)),
        )

    @property
    def usable(self) -> bool:
        return bool(self.text)


class PhotoInspectOut(BaseModel):
    """上传图体检结果。"""

    model_config = ConfigDict(extra="ignore")

    is_shoe: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    shoe_count: int = Field(default=0, ge=0, le=50)
    subject_description: str = Field(default="", max_length=40)
    brand: str = Field(default="", max_length=40)
    model_name: str = Field(default="", max_length=80)
    colorway: str = Field(default="", max_length=40)
    #: 拍摄视角：lateral（正侧面，唯一能画的）/ three_quarter / top / other；空串 = 老记录
    view: str = Field(default="", max_length=20)
    #: 鞋头朝向：left / right / unknown；空串 = 老记录
    facing: str = Field(default="", max_length=10)
    #: 整只鞋是否都在画面里（被切掉鞋头或鞋跟时为 False）
    complete: bool = True
    logo: LogoInfo = Field(default_factory=LogoInfo)
    texts: list[ShoeText] = Field(default_factory=list, max_length=8)
    notes: str = Field(default="", max_length=200)

    @field_validator("subject_description", "brand", "model_name", "colorway", "notes", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("view", mode="before")
    @classmethod
    def _clean_view(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip().lower()
        aliases = {
            "side": "lateral", "profile": "lateral", "正侧面": "lateral", "侧面": "lateral",
            "3/4": "three_quarter", "three-quarter": "three_quarter", "斜侧": "three_quarter",
            "top": "top", "topdown": "top", "俯视": "top", "bird": "top",
        }
        text = aliases.get(text, text)
        return text if text in {"lateral", "three_quarter", "top", "other"} else ""

    @field_validator("facing", mode="before")
    @classmethod
    def _clean_facing(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip().lower()
        aliases = {"左": "left", "right_side": "right", "右": "left" if False else "right"}
        text = aliases.get(text, text)
        return text if text in {"left", "right", "unknown"} else ""

    @field_validator("logo", mode="before")
    @classmethod
    def _logo_from_none(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("texts", mode="before")
    @classmethod
    def _texts_from_none(cls, value: Any) -> Any:
        return [] if value is None else value

    @property
    def tier(self) -> str:
        """三档判定：shoe（明确是鞋）/ not_shoe（明确不是鞋）/ uncertain（不确定，放行）。"""
        if self.is_shoe and self.confidence >= UNCERTAIN_CONFIDENCE:
            return "shoe"
        if not self.is_shoe and self.confidence >= UNCERTAIN_CONFIDENCE:
            return "not_shoe"
        return "uncertain"

    @property
    def is_side_view(self) -> bool:
        """是不是正侧面。**空串（老记录/模型没给）一律当作可以画** —— 宁可放行让人自己判断，
        也不要因为一个新字段缺失就把原来能跑的流程卡住。"""
        return self.view in ("", "lateral")

    @property
    def needs_mirror(self) -> bool:
        """鞋头朝右 → 生成后镜像一次，保证鞋柜里每双都朝左（产品反馈 7）。"""
        return self.facing == "right"

    @property
    def display_name(self) -> str:
        """归档标题用的名字（自动命名）。"""
        parts = [p for p in (self.brand, self.model_name) if p]
        return " ".join(parts)

    @property
    def drawable_texts(self) -> list[str]:
        """交给生图提示词的文字清单（去重、保持顺序）。"""
        seen: list[str] = []
        for item in self.texts:
            if item.usable and item.text not in seen:
                seen.append(item.text)
        return seen
