"""模型结构化输出结构（强校验）：型号校对、质检、候选排序。

工程约定：模型输出必须经过结构校验，不能假设模型总会返回正确格式。
分数越界、字段类型错误、issues 非列表 -> 直接拒绝（由上层决定重试还是报错）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=120)


class ModelResolveOut(BaseModel):
    """`resolve_model` 的输出（对应 prompts/resolve_model.md）。"""

    model_config = ConfigDict(extra="ignore")

    normalized: str = Field(default="", max_length=80)
    brand: str = Field(default="", max_length=40)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    exists: bool = False
    candidates: list[ModelCandidate] = Field(default_factory=list, max_length=5)
    note: str = Field(default="", max_length=200)

    @field_validator("normalized", "brand", "note", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def _enforce_no_fabrication(self) -> ModelResolveOut:
        """禁止编造型号：不存在时必须给出相近候选且 normalized 留空。"""
        if self.confidence < 0.5:
            self.exists = False
        if not self.exists:
            if not self.candidates:
                raise ValueError("exists=false 时必须提供 candidates 相近候选")
            self.normalized = ""
        else:
            if not self.normalized:
                raise ValueError("exists=true 时 normalized 不能为空")
        return self


class QualityReportOut(BaseModel):
    """`verify_lineart` 中视觉模型的输出（canvas_ratio 由代码判定，不在此结构内）。"""

    model_config = ConfigDict(extra="ignore")

    shoe_silhouette_match: float = Field(ge=0.0, le=1.0)
    logo_legibility: float = Field(ge=0.0, le=1.0)
    style_consistency: float = Field(ge=0.0, le=1.0)
    noise_level: float = Field(ge=0.0, le=1.0)
    #: Logo 是否被**实心填充**（0=空心轮廓 / 1=正确填实）。硬闸门：标志性图形必须填实。
    logo_filled: float = Field(default=1.0, ge=0.0, le=1.0)
    #: 鞋带被涂成实心块的程度（0=无 / 1=全实心）。硬上限：鞋带不得实心。
    laces_solid_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    #: 鞋身文字可辨度（软性）：不达标只触发兜底贴合，不决定成败。
    text_legible: float = Field(default=1.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list, max_length=10)
    verdict: str = Field(default="", max_length=20)
    reason: str = Field(default="", max_length=300)

    @field_validator("issues", mode="before")
    @classmethod
    def _issues_must_be_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raise ValueError("issues 必须是字符串列表")
        if not isinstance(value, list):
            raise ValueError("issues 必须是字符串列表")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("issues 里每一项都必须是字符串")
            out.append(item.strip()[:200])
        return out

    @field_validator(
        "shoe_silhouette_match",
        "logo_legibility",
        "style_consistency",
        "noise_level",
        "logo_filled",
        "laces_solid_ratio",
        "text_legible",
    )
    @classmethod
    def _finite_scores(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):  # NaN / Inf
            raise ValueError("分数必须是有限数字")
        return value

    @field_validator("verdict", "reason", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()


class SourceRankOut(BaseModel):
    """`rank_source_images` 的可选模型排序输出。"""

    model_config = ConfigDict(extra="ignore")

    order: list[int] = Field(default_factory=list, max_length=10)
    reasons: dict[str, str] = Field(default_factory=dict)


class SourceScreenItem(BaseModel):
    """单张候选图的可用性判断。"""

    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0, le=9)
    single_shoe: bool = False
    side_view: bool = False
    clean_background: bool = False
    sharp: bool = False
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()[:200]

    def flags(self) -> dict:
        return {
            "single_shoe": self.single_shoe,
            "side_view": self.side_view,
            "clean_background": self.clean_background,
            "sharp": self.sharp,
        }


class SourceScreenOut(BaseModel):
    """`screen_source_images` 的输出。"""

    model_config = ConfigDict(extra="ignore")

    results: list[SourceScreenItem] = Field(default_factory=list, max_length=10)
    best_index: int = Field(default=-1, ge=-1, le=9)

    @model_validator(mode="after")
    def _best_index_in_results(self) -> SourceScreenOut:
        if self.best_index >= 0 and self.best_index not in {item.index for item in self.results}:
            self.best_index = -1
        return self
