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
    quality: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    upstream_calls: int = 0
    est_cost_cny: float = 0.0
    can: dict[str, bool] = Field(default_factory=dict)


class TaskActionOut(BaseModel):
    task_id: str
    state: TaskState
    message: str = ""
