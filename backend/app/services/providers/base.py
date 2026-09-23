"""上游提供方协议 + 调用记录（成本护栏）。

设计说明（对应内部工程笔记 4.4）：这里不实现“开放式 Agent Loop”，而是把模型能力
包成 4 个**任务型**提供方：型号校对器、质检员、线稿生成器、搜图器。真实实现负责
组装 Prompt 并调用火山方舟；mock 实现负责离线给出确定性结果，二者可互换。

`CallRecorder` 是成本护栏的确定性实现：每次调用前 check()，超过上限直接
BUDGET_EXCEEDED（不依赖模型自律）。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol, runtime_checkable

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.schemas.inspect import PhotoInspectOut
from app.schemas.llm import ModelResolveOut, QualityReportOut, SourceScreenOut
from app.schemas.task import SourceCandidate
from app.services.style.loader import StyleTemplate

CallKind = Literal["text", "vision", "image", "search"]


@dataclass
class CallRecord:
    kind: CallKind
    provider: str
    model: str = ""
    duration_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    est_cost_cny: float = 0.0
    ok: bool = True
    error_code: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "error_code": self.error_code,
            "est_cost_cny": round(self.est_cost_cny, 4),
            **self.detail,
        }


class CallRecorder:
    """单任务的**任务级**上游调用计数与成本估算（硬上限，见阶段文档 3.3）。

    注意：计数是任务级的，不按阶段重置 —— 流水线重启/重生成时必须把已用量传进来
    （`used_calls` / `used_cost`），否则成本护栏会被绕过。
    """

    def __init__(
        self,
        max_calls: int,
        settings: Settings,
        *,
        used_calls: int = 0,
        used_cost: float = 0.0,
    ) -> None:
        self.max_calls = max_calls
        self.settings = settings
        self.calls: list[CallRecord] = []
        self.used_calls = max(0, used_calls)
        self.used_cost = max(0.0, used_cost)

    # ---- 护栏 ----
    def check(self, kind: CallKind) -> None:
        if self.total_calls >= self.max_calls:
            raise AppError(
                ErrorCode.BUDGET_EXCEEDED,
                detail={"max_calls": self.max_calls, "next_call": kind},
            )

    def record(
        self,
        kind: CallKind,
        *,
        provider: str,
        model: str = "",
        duration_ms: int = 0,
        ok: bool = True,
        error_code: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> CallRecord:
        cost = {
            "text": self.settings.cost_per_text_call,
            "vision": self.settings.cost_per_vision_call,
            "image": self.settings.cost_per_image_call,
            "search": 0.0,
        }[kind]
        record = CallRecord(
            kind=kind,
            provider=provider,
            model=model,
            duration_ms=duration_ms,
            detail=detail or {},
            est_cost_cny=cost,
            ok=ok,
            error_code=error_code,
        )
        self.calls.append(record)
        return record

    @property
    def total_calls(self) -> int:
        return self.used_calls + len(self.calls)

    @property
    def total_cost(self) -> float:
        return round(self.used_cost + sum(c.est_cost_cny for c in self.calls), 4)

    def traces(self) -> list[dict[str, Any]]:
        return [c.to_trace() for c in self.calls]


@contextmanager
def timer() -> Iterator[dict[str, int]]:
    box = {"ms": 0}
    start = time.perf_counter()
    try:
        yield box
    finally:
        box["ms"] = int((time.perf_counter() - start) * 1000)


# --------------------------------------------------------------------------- 协议
@runtime_checkable
class ModelResolver(Protocol):
    name: str
    model: str
    mode: Literal["mock", "real"]

    def resolve(
        self, raw_query: str, known_brands: list[str], recorder: CallRecorder
    ) -> ModelResolveOut: ...


@runtime_checkable
class QualityJudge(Protocol):
    name: str
    model: str
    mode: Literal["mock", "real"]

    def judge(
        self,
        *,
        model_name: str,
        style: StyleTemplate,
        source_png: bytes | None,
        artwork_png: bytes,
        recorder: CallRecorder,
    ) -> QualityReportOut: ...

    def screen_sources(
        self,
        *,
        images: list[bytes],
        model_name: str,
        recorder: CallRecorder,
    ) -> SourceScreenOut: ...

    def inspect_photo(
        self,
        *,
        image: bytes,
        recorder: CallRecorder,
    ) -> PhotoInspectOut: ...


@runtime_checkable
class LineartGenerator(Protocol):
    name: str
    model: str
    mode: Literal["mock", "real"]

    def generate(
        self,
        *,
        canvas_png: bytes | None,
        style: StyleTemplate,
        attempt: int,
        recorder: CallRecorder,
        structure_reference: bytes | None = None,
        model_name: str | None = None,
        logo_fill: str | None = None,
        shoe_texts: list[str] | None = None,
    ) -> bytes: ...


@runtime_checkable
class ShoeImageSearch(Protocol):
    name: str
    mode: Literal["mock", "real"]

    def search(
        self, *, model_name: str, limit: int, recorder: CallRecorder
    ) -> list[SourceCandidate]: ...


@dataclass
class ProviderBundle:
    resolver: ModelResolver
    judge: QualityJudge
    generator: LineartGenerator
    search: ShoeImageSearch
    mode: Literal["mock", "real"]
    missing: list[str] = field(default_factory=list)

    @property
    def search_credential_ok(self) -> bool:
        return self.search.mode == "real"


def build_providers(settings: Settings, *, known_brands: list[str] | None = None) -> ProviderBundle:
    """按配置装配提供方：有 Key 且未强制 mock -> 真实上游；否则 mock。"""
    if settings.use_mock_providers:
        from app.services.providers.mock import (
            MockLineartGenerator,
            MockModelResolver,
            MockQualityJudge,
            MockShoeImageSearch,
        )

        return ProviderBundle(
            resolver=MockModelResolver(),
            judge=MockQualityJudge(settings),
            generator=MockLineartGenerator(settings),
            search=MockShoeImageSearch(),
            mode="mock",
            missing=settings.missing_ark_config,
        )

    from app.services.providers.ark_image import ArkLineartGenerator
    from app.services.providers.ark_text import ArkModelResolver
    from app.services.providers.ark_vision import ArkQualityJudge
    from app.services.providers.volc_image_search import VolcImageSearchProvider

    missing = [name for name, value in (("ARK_API_KEY", settings.ark_api_key),) if not value]
    if not settings.ark_text_model:
        missing.append("ARK_TEXT_MODEL")
    if not settings.ark_vision_model:
        missing.append("ARK_VISION_MODEL")
    if not settings.ark_image_model:
        missing.append("ARK_IMAGE_MODEL")
    if missing:
        raise AppError(
            ErrorCode.UPSTREAM_AUTH_FAILED,
            message="模型配置不完整，请在 .env 补齐：" + "、".join(missing),
            detail={"missing": missing},
        )

    search: ShoeImageSearch
    if settings.search_provider == "mock" or not settings.search_credentials_present:
        from app.services.providers.mock import MockShoeImageSearch

        search = MockShoeImageSearch()
    else:
        search = VolcImageSearchProvider(settings)

    return ProviderBundle(
        resolver=ArkModelResolver(settings),
        judge=ArkQualityJudge(settings),
        generator=ArkLineartGenerator(settings),
        search=search,
        mode="real",
        missing=[],
    )
