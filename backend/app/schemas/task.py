"""任务相关请求/响应结构与任务记录（持久化到 owners/{owner_id}/tasks/{task_id}.json）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import TaskState


# --------------------------------------------------------------------------- 请求
class TaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=60)
    style_id: str | None = Field(default=None, max_length=40)

    @field_validator("query")
    @classmethod
    def _clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("型号不能为空")
        return cleaned

    @field_validator("style_id")
    @classmethod
    def _clean_style(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SourceSelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_index: int | None = Field(default=None, ge=0, le=4)
    manual_url: str | None = Field(default=None, max_length=1000)
    manual_path: str | None = Field(default=None, max_length=500)
    #: 兜底路径：候选图都不适合当参考时，直接用"型号知识"生成线稿（界面上的
    #: 「这些图都不合适，直接用型号生成」）
    use_model_only: bool = False

    @model_validator(mode="after")
    def _at_most_one(self) -> SourceSelectIn:
        provided = [
            self.selected_index is not None,
            bool(self.manual_url),
            bool(self.manual_path),
            self.use_model_only,
        ]
        if sum(provided) > 1:
            raise ValueError("请只提供 selected_index / manual_url / manual_path / use_model_only 其中之一")
        # 全都不给 = 「就用你推荐的那张」（界面上的「就是这双，开始画」）
        return self


class CropBox(BaseModel):
    """上传图裁切框（原图坐标 x,y,w,h）。"""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


class TextStamp(BaseModel):
    """鞋身文字的可定位信息（文字兜底贴合用）。

    ``box`` 是相对**体检裁切图**的归一化边界框 ``[x, y, w, h]``（均 ∈ [0,1]）。
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
        if w <= 0.01 or h <= 0.01:
            return None
        return (
            max(0.0, min(1.0, x)),
            max(0.0, min(1.0, y)),
            min(1.0, max(0.0, w)),
            min(1.0, max(0.0, h)),
        )


class InspectHints(BaseModel):
    """上传图体检结果里、供「生成」与「归档命名」复用的那部分。

    前端在 ``POST /inspect``（带裁切框）拿到三档结论与品牌/型号/Logo/文字后，
    确认要画，就把这些信息原样带回 ``POST /tasks/upload`` —— 后端不再二次调用视觉模型。
    """

    model_config = ConfigDict(extra="ignore")

    display_name: str = Field(default="", max_length=120)
    brand: str = Field(default="", max_length=40)
    model_name: str = Field(default="", max_length=80)
    colorway: str = Field(default="", max_length=40)
    logo_type: str = Field(default="", max_length=60)
    logo_position: str = Field(default="", max_length=60)
    logo_fill_required: bool = True
    texts: list[str] = Field(default_factory=list, max_length=8)
    #: 带定位信息的文字（box 相对体检裁切图）—— 文字兜底贴合用
    text_stamps: list[TextStamp] = Field(default_factory=list, max_length=8)
    shoe_count: int = Field(default=1, ge=0, le=50)

    @field_validator("display_name", "brand", "model_name", "colorway", "logo_type", "logo_position", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("texts", mode="before")
    @classmethod
    def _clean_texts(cls, value: Any) -> list[str]:
        if value is None:
            return []
        seen: list[str] = []
        for item in value:
            text = "" if item is None else str(item).strip()
            if text and text not in seen:
                seen.append(text)
            if len(seen) >= 8:
                break
        return seen

    @property
    def logo_fill_hint(self) -> str:
        """写进生图提示词的 Logo 填色描述（形状 + 位置）。"""
        if not self.logo_type:
            return ""
        if self.logo_position:
            return f"{self.logo_type}（{self.logo_position}）"
        return self.logo_type

    @property
    def name_for_archive(self) -> str:
        """归档标题用的默认名：品牌 + 型号，缺失时退回 display_name。"""
        parts = [p for p in (self.brand, self.model_name) if p]
        return " ".join(parts) or self.display_name


class UploadTaskCreateIn(BaseModel):
    """上传图生成（V2 输入方式）：图 + 裁切框 + 已体检结论。"""

    model_config = ConfigDict(extra="forbid")

    #: 原图 base64（可带 data:image/...;base64, 前缀）
    image_base64: str = Field(min_length=32)
    crop: CropBox
    inspect: InspectHints = Field(default_factory=InspectHints)
    style_id: str | None = Field(default=None, max_length=40)

    @field_validator("style_id")
    @classmethod
    def _clean_style(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class RegenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=200)


class ArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_text: str | None = Field(default=None, max_length=40)
    story: str | None = Field(default=None, max_length=2000)
    model_name: str | None = Field(default=None, max_length=80)
    attempt: int | None = Field(default=None, ge=1, le=99)

    @field_validator("date_text", "story", "model_name")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


# --------------------------------------------------------------------------- 任务记录
class SourceCandidate(BaseModel):
    # extra="allow"：保留上游返回的额外信号（blur/watermark/shape/rank_score...），
    # 它们既用于选图排序，也随任务文件持久化，便于排错与回溯
    model_config = ConfigDict(extra="allow")

    index: int
    provider: str = "unknown"
    url: str | None = None
    local_path: str | None = None
    width: int | None = None
    height: int | None = None
    rank: int | None = None
    credit: str = "图源来自公开检索"


class ResolveInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    normalized: str = ""
    brand: str = ""
    confidence: float = 0.0
    exists: bool = False
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidates: list[SourceCandidate] = Field(default_factory=list)
    #: single = 已命中，只给一张推荐图；choose = 系统不确定，展开多张让用户挑
    mode: str = "single"
    recommended_index: int = 0
    selected_index: int | None = None
    selected_provider: str | None = None
    selected_url: str | None = None
    manual: bool = False
    source_path: str | None = None
    #: 是否走"型号直出"（不使用参考图；搜到的图只用于质检比对）
    use_model_only: bool = False
    #: 源图预筛结果（可用性判断与理由），用于界面解释"为什么推荐这张"
    screen: dict[str, Any] = Field(default_factory=dict)


class ArtworkCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    attempt: int
    path: str
    score: float | None = None
    passed: bool | None = None
    issues: list[str] = Field(default_factory=list)
    created_at: str = ""


class Attempts(BaseModel):
    model_config = ConfigDict(extra="allow")

    round: int = 0
    used_in_round: int = 0
    total: int = 0


class QualityInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: float | None = None
    attempts: int = 0
    checks: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    verdict: str | None = None
    best_attempt: int | None = None
    artwork_check: dict[str, Any] = Field(default_factory=dict)


class TaskError(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    task_id: str
    owner_id: str
    state: TaskState = TaskState.CREATED
    created_at: str
    updated_at: str
    style_id: str = "bw_lineart"
    query: str = ""
    resolve: ResolveInfo = Field(default_factory=ResolveInfo)
    source: SourceInfo = Field(default_factory=SourceInfo)
    artworks: list[ArtworkCandidate] = Field(default_factory=list)
    attempts: Attempts = Field(default_factory=Attempts)
    quality: QualityInfo = Field(default_factory=QualityInfo)
    error: TaskError | None = None
    upstream_calls: int = 0
    est_cost_cny: float = 0.0
    trace_id: str = ""
    progress: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    #: 上传图体检结论（V2）：Logo 填色要求、鞋身文字清单、归档命名来源
    inspect: InspectHints | None = None
    #: 文字兜底贴片（预处理阶段从原图裁出）：[{"box": [x,y,w,h], "path": "text_stamp_0.png"}, ...]
    text_stamps: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- 响应
class ArtworkOut(BaseModel):
    attempt: int
    url: str
    score: float | None = None
    passed: bool | None = None
    issues: list[str] = Field(default_factory=list)


class TaskOut(BaseModel):
    task_id: str
    state: TaskState
    query: str
    style_id: str
    created_at: str
    updated_at: str
    progress: dict[str, Any] = Field(default_factory=dict)
    normalize: dict[str, Any] | None = None
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    #: single / choose —— 决定界面是「确认是这双吗」还是「请选一张」
    source_mode: str = "single"
    recommended_index: int = 0
    source_screen: dict[str, Any] = Field(default_factory=dict)
    selected_index: int | None = None
    artworks: list[ArtworkOut] = Field(default_factory=list)
    current_artwork_url: str | None = None
    #: CV 草稿（边缘骨架图）地址；AI 生成中用它做「扫过式揭示」动效。型号直出时为 None。
    draft_url: str | None = None
    quality: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    upstream_calls: int = 0
    est_cost_cny: float = 0.0
    can: dict[str, bool] = Field(default_factory=dict)


class TaskActionOut(BaseModel):
    task_id: str
    state: TaskState
    message: str = ""
