"""风格模板加载与校验（s07 技能加载）。

本阶段只注册 `bw_lineart`，但架构上做成可注册：新增风格 = 新增一个 YAML，
不改主干代码（PRD Step 0.2 / Roadmap 方向 2）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import AppError, ErrorCode


class CanvasSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    aspect_ratio: str = "3:2"
    view: str = "lateral"
    direction: str = "toe_left"
    padding: str = "8%"
    background: str = "white"
    overlay_text: str = "none"

    @property
    def padding_ratio(self) -> float:
        return float(self.padding.strip().rstrip("%")) / 100.0

    @property
    def width_height(self) -> tuple[int, int]:
        left, right = self.aspect_ratio.split(":")
        return int(left), int(right)


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    positive: str = Field(min_length=1)
    negative: str = Field(min_length=1)


class QualityGate(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks: list[str]
    weights: dict[str, float]
    hard_gate: dict[str, float] = Field(default_factory=dict)
    min_score: float = 0.80
    #: 风格一致性闸门：metric -> [low, high]，由参考图量化得出，由代码判定
    style_metrics: dict[str, list[float]] = Field(default_factory=dict)

    @field_validator("checks")
    @classmethod
    def _checks_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("quality_gate.checks 不能为空")
        return value


class StyleTemplate(BaseModel):
    model_config = ConfigDict(extra="allow")

    style_id: str = Field(min_length=1, max_length=40)
    name: str = ""
    version: int = 1
    reference_images: list[str] = Field(default_factory=list)
    canvas: CanvasSpec
    prompt: PromptSpec
    constraints: dict = Field(default_factory=dict)
    provider_params: dict = Field(default_factory=dict)
    postprocess: dict = Field(default_factory=dict)
    quality_gate: QualityGate

    def style_rules_text(self) -> str:
        """注入质检 Prompt 的“风格规则”文本。"""
        return (
            f"风格：{self.name}；画布比例 {self.canvas.aspect_ratio}；"
            f"视角 {self.canvas.view}，鞋头方向 {self.canvas.direction}；"
            f"背景 {self.canvas.background}；不叠加任何文字。\n"
            f"正向要求：{self.prompt.positive.strip()}\n"
            f"禁止项：{self.prompt.negative.strip()}"
        )


def load_template(path: Path) -> StyleTemplate:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(ErrorCode.STYLE_NOT_FOUND, detail={"path": path.name}) from exc
    except yaml.YAMLError as exc:
        raise AppError(
            ErrorCode.STYLE_NOT_FOUND,
            message=f"风格模板 {path.name} 不是合法 YAML，请修好后再试。",
        ) from exc
    if not isinstance(raw, dict):
        raise AppError(ErrorCode.STYLE_NOT_FOUND, detail={"path": path.name})
    try:
        return StyleTemplate.model_validate(raw)
    except Exception as exc:
        raise AppError(
            ErrorCode.STYLE_NOT_FOUND,
            message=f"风格模板 {path.name} 缺少必填字段，请补齐后再试。",
        ) from exc
