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
    #: 硬上限闸门：value > 上限 -> 不合格（如 laces_solid_ratio 鞋带不得实心）
    hard_max: dict[str, float] = Field(default_factory=dict)
    #: 风格指标的硬闸门：**只把**这些 key 的偏离当不合格，其余 style_metrics 只报告
    style_hard_keys: list[str] = Field(default_factory=list)
    #: 风格指标的硬上限（如「大面积涂黑」上限）：value > 上限 -> 不合格
    style_hard_max: dict[str, float] = Field(default_factory=dict)
    #: 风格指标的**硬下限**：value < 下限 -> 不合格。
    #: 用途：「整双鞋太轻 / 一块实色都没有」。
    #: 为什么不交给视觉模型判：2026-09-24 实测，判官给一张勾没填的画稿打了
    #: `logo_filled = 1.0`（它的提示词里有"看不到标识就按 1.0"的宽容条款，被过度套用了），
    #: 于是那张不合格的稿子直接过关、不会触发重画。填色这类可量化的事由代码判。
    style_floor: dict[str, float] = Field(default_factory=dict)
    #: 轮廓重合度下限（0 = 关闭）。由 `cv/silhouette.py` 确定性计算，
    #: 用于抳下"鞋头/前掌整块没画出来"这类塌陷（2026-09-24 的 PG4）。
    silhouette_floor: float = 0.0
    #: 用哪份判官提示词（默认黑白那份；水彩用 verify_watercolor.md）
    judge_prompt: str = ""
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
    #: 是否对用户隐藏。隐藏的风格：不出现在风格列表、不能用来建新任务，
    #: 但**文件和代码全留着** —— 老档案还要按它渲染，将来想启用改这一个字段即可。
    #: （2026-09-24：这一版主风格切成水彩，黑白线稿先隐藏，后续再回来做。）
    hidden: bool = False
    reference_images: list[str] = Field(default_factory=list)
    canvas: CanvasSpec
    prompt: PromptSpec
    constraints: dict = Field(default_factory=dict)
    provider_params: dict = Field(default_factory=dict)
    postprocess: dict = Field(default_factory=dict)
    quality_gate: QualityGate

    @property
    def judge_prompt(self) -> str:
        """用哪份判官提示词。不同风格的"合格"标准不一样，判官也必须换。

        黑白那份按"纯二值、Logo 纯黑实心"来打分；拿它判水彩会把正确产出判成不合格
        （实测：它给水彩的 `style_consistency` 打分没有参考价值），所以按风格分开。
        """
        return str(self.quality_gate.judge_prompt or "verify_lineart.md")

    @property
    def needs_structure_reference(self) -> bool:
        """要不要把"白底黑线的骨架图"当第二张参考图喂给生图模型。

        黑白线稿风格要（等效 ControlNet 边缘引导，锁住结构）；
        **彩色风格（水彩）不要** —— 那张骨架就是一套黑线，喂进去模型会照着勾线，
        而水彩的要求恰恰是"不要用粗黑勾线定义整双鞋、不要形成线稿+上色的观感"。
        """
        return str(self.constraints.get("structure_control", "controlnet_edge")) != "none"

    @property
    def binarize(self) -> bool:
        """后处理是否二值化。黑白线稿风格为 True；彩色风格（水彩）必须为 False。

        放在风格模板里而不是代码里：二值化是**风格的要求**，不是管线的固有步骤
        （同一套后处理要服务两种风格，见 tools/refine_lineart.py）。
        """
        return bool(self.postprocess.get("binarize", True))

    @property
    def canvas_background(self) -> str:
        """画稿补边用的底色：黑白稿是纯白，水彩是暖白纸色。"""
        default = "#ffffff" if self.binarize else "#faf6f0"
        return str(self.postprocess.get("canvas_background") or default)

    @property
    def background_ratio_floor(self) -> float:
        """背景留白下限。黑白稿要求 0.60（白底为主）；水彩靠纸色留白，0.45 就够。"""
        return float(self.postprocess.get("min_background_ratio", 0.60 if self.binarize else 0.45))

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
