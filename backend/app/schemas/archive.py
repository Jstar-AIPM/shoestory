"""鞋柜档案结构（`owners/{owner_id}/archive.json`，schema_version=1）。

字段定义与《第 1 阶段技术开发文档》6.2 完全一致。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import RIGHTS_NOTE


class ArtworkMeta(BaseModel):
    """画稿元数据。**不再假设"一定是二值白底"** —— 彩色风格（水彩）是连续色调 + 纸底。"""

    model_config = ConfigDict(extra="allow")

    width: int
    height: int
    ratio: str = "3:2"
    #: 是否纯二值。黑白线稿为 True；水彩等彩色风格为 False
    binary: bool = True
    #: 底色：`white`（黑白稿）或 `paper`（水彩的暖白纸底）
    background: str = "white"
    has_text_overlay: bool = False
    white_ratio: float | None = None
    #: 与底色的接近程度（非二值风格用它判"留白够不够"）
    background_ratio: float | None = None


class ArchiveSource(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = "unknown"
    url: str | None = None
    credit: str = "图源来自公开检索"
    selected_by: str = "user"


class ArchiveQuality(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: float | None = None
    attempts: int = 0
    checks: dict[str, float] = Field(default_factory=dict)


class ArchiveItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    shoe_id: str
    owner_id: str
    model_name: str = Field(min_length=1, max_length=80)
    model_name_input: str = Field(default="", max_length=80)
    artwork_path: str
    artwork_meta: ArtworkMeta
    date_text: str | None = Field(default=None, max_length=40)
    date_sort_key: str | None = None
    story: str | None = Field(default=None, max_length=2000)
    manual_order: int | None = None
    created_at: str
    style_id: str = "bw_lineart"
    style_version: int = 1
    source: ArchiveSource = Field(default_factory=ArchiveSource)
    quality: ArchiveQuality = Field(default_factory=ArchiveQuality)
    trace_id: str = ""
    rights_note: str = RIGHTS_NOTE

    @field_validator("artwork_path")
    @classmethod
    def _artwork_path_must_be_owned(cls, value: str) -> str:
        if ".." in value or value.startswith("/"):
            raise ValueError("artwork_path 必须是受控相对路径")
        return value

    @model_validator(mode="after")
    def _artwork_path_matches_owner(self) -> ArchiveItem:
        expected_prefix = f"owners/{self.owner_id}/"
        if not self.artwork_path.startswith(expected_prefix):
            raise ValueError("artwork_path 与 owner_id 不匹配")
        return self


class ArchiveFile(BaseModel):
    """archive.json 的整体结构。"""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    updated_at: str = ""
    items: list[ArchiveItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- API 结构
class ArchiveListOut(BaseModel):
    shoe_id: str
    model_name: str
    artwork_url: str
    #: 这双鞋当初用哪个风格画的 —— 鞋柜里可能新旧混着，卡片要按各自风格渲染
    #: （黑白稿需要叠一层牛皮纸，水彩稿自带纸色、叠了会被染成褐色）
    style_id: str = "bw_lineart"
    date_text: str | None = None
    date_sort_key: str | None = None
    created_at: str
    has_story: bool = False


class ArchiveListResponse(BaseModel):
    total: int
    items: list[ArchiveListOut]
    warning: str | None = None


class ArchiveItemOut(BaseModel):
    shoe_id: str
    model_name: str
    model_name_input: str = ""
    artwork_url: str
    artwork_meta: dict[str, Any] = Field(default_factory=dict)
    date_text: str | None = None
    date_sort_key: str | None = None
    story: str | None = None
    created_at: str
    style_id: str = "bw_lineart"
    style_version: int = 1
    source: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    rights_note: str = RIGHTS_NOTE
    # 详情页翻页（“上一双 / 下一双”）：服务端按当前排序算好，避免前端分页边界问题
    position: int | None = None
    total: int | None = None
    prev_shoe_id: str | None = None
    next_shoe_id: str | None = None


class ArchivePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str | None = Field(default=None, max_length=80)
    date_text: str | None = Field(default=None, max_length=40)
    story: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _at_least_one(self) -> ArchivePatchIn:
        if self.model_name is None and self.date_text is None and self.story is None:
            raise ValueError("至少提供一个要修改的字段")
        if self.model_name is not None and not self.model_name.strip():
            raise ValueError("型号不能改成空")
        return self


class ArchiveCreateOut(BaseModel):
    shoe_id: str
    artwork_url: str
    date_sort_key: str | None = None
    created_at: str


class DeleteOut(BaseModel):
    deleted: bool = True
    removed_files: int = 0
