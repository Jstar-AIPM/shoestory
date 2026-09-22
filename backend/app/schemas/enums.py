"""共享枚举：任务状态、质检项、存储 key 前缀。"""

from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    """任务状态（唯一真相见 services/workflow/state_machine.py）。

    兼容策略：只允许追加，不得复用旧状态语义。
    """

    CREATED = "created"
    RESOLVING = "resolving"
    #: 型号已校对、正在文搜图 + 视觉预筛（线上实测约 58s，因此必在后台跑，不能占着请求）
    SEARCHING_SOURCE = "searching_source"
    MODEL_NOT_FOUND = "model_not_found"
    RESOLVE_FAILED = "resolve_failed"
    AWAITING_SOURCE_CONFIRM = "awaiting_source_confirm"
    PREPROCESSING = "preprocessing"
    GENERATING = "generating"
    REFINING = "refining"
    VERIFYING = "verifying"
    INTERRUPTED = "interrupted"
    AWAITING_EFFECT_CONFIRM = "awaiting_effect_confirm"
    ARCHIVING = "archiving"
    ARCHIVED = "archived"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualityCheck(str, Enum):
    SHOE_SILHOUETTE_MATCH = "shoe_silhouette_match"
    LOGO_LEGIBILITY = "logo_legibility"
    STYLE_CONSISTENCY = "style_consistency"
    NOISE_LEVEL = "noise_level"
    CANVAS_RATIO = "canvas_ratio"


RIGHTS_NOTE = "个人纪念性再创作，商标归原品牌所有"
SOURCE_CREDIT = "图源来自公开检索"

ARTWORK_FILENAME = "artwork.png"
STAGING_ARTWORK_TEMPLATE = "artwork_a{attempt}.png"
