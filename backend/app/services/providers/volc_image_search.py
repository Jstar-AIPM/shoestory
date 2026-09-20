"""火山引擎 · 豆包搜索 Custom 版（文搜图）适配层。

接口契约已按官方文档逐字核对（docs.volcengine.com/docs/87772/2272953）：

- 地址：POST https://open.feedcoopapi.com/search_api/web_search
- 鉴权：header `Authorization: Bearer {API_KEY}`（API Key 接入，推荐）
- 请求：Query（1~100 字符）、SearchType="image"、Count（最多 5）、
        Filter{ImageWidthMin/ImageHeightMin/ImageShapes:[横长方形|竖长方形|方形]}、
        QueryControl{QueryRewrite}
- 响应：Result.ImageResults[].Image{Url,Width,Height,Shape,BlurDes,Watermark}
        + ResponseMetadata.Error（接口层错误）
- 计费：每账号每月 500 次免费（优先消耗），账号级 10 QPS

关键设计：官方返回的 `BlurDes`（清晰/一般清晰/模糊）与 `Watermark`（1/0）
是**免费的选图信号**，比让模型猜“哪张更清楚”更可靠，因此透传给排序环节。
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.schemas.enums import SOURCE_CREDIT
from app.schemas.task import SourceCandidate
from app.services.providers.base import CallRecorder, timer

DEFAULT_ENDPOINT = "https://open.feedcoopapi.com/search_api/web_search"


class VolcImageSearchProvider:
    name = "volc_doubao"
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.endpoint = settings.volc_search_endpoint or DEFAULT_ENDPOINT

    # ---- 请求体（按官方字段名）----
    def _build_payload(self, model_name: str, limit: int) -> dict:
        payload: dict = {
            "Query": model_name[:100],  # 官方限制 1~100 字符
            "SearchType": "image",
            "Count": max(1, min(limit, 5)),  # 官方最多 5 条
            "Filter": {
                "ImageWidthMin": self.settings.search_image_width_min,
                "ImageShapes": [self.settings.search_image_shape],
            },
            "QueryControl": {"QueryRewrite": False},  # 改写会增加耗时，默认关闭
        }
        return payload

    # ---- 响应解析（Result.ImageResults[].Image）----
    def _parse_response(self, data: dict, limit: int) -> list[SourceCandidate]:
        meta = data.get("ResponseMetadata") or {}
        error = meta.get("Error") if isinstance(meta, dict) else None
        if error:
            code = str(error.get("Code") or "")
            message = str(error.get("Message") or "")
            lowered = code.lower()
            if any(
                token in lowered
                for token in ("auth", "credential", "permission", "denied", "forbidden", "access")
            ):
                raise AppError(ErrorCode.UPSTREAM_AUTH_FAILED, detail={"upstream": code})
            raise AppError(
                ErrorCode.IMAGE_SEARCH_FAILED,
                detail={"upstream": code, "message": message[:120]},
            )

        result = data.get("Result")
        if not isinstance(result, dict):
            return []
        items = result.get("ImageResults")
        if not isinstance(items, list):
            return []

        candidates: list[SourceCandidate] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            image = item.get("Image")
            if not isinstance(image, dict):
                continue
            url = image.get("Url")
            if not url:
                continue
            index = len(candidates)
            candidates.append(
                SourceCandidate(
                    index=index,
                    provider=self.name,
                    url=str(url),
                    width=_int_or_none(image.get("Width")),
                    height=_int_or_none(image.get("Height")),
                    credit=SOURCE_CREDIT,
                    landing_url=item.get("Url"),
                    site_name=item.get("SiteName"),
                    title=item.get("Title"),
                    shape=image.get("Shape"),
                    blur=image.get("BlurDes"),
                    watermark=image.get("Watermark"),
                    rank_score=item.get("RankScore"),
                    # 便于排错：本次搜索的真实耗时与日志号（不含敏感信息）
                    upstream_time_cost_ms=result.get("TimeCost"),
                )
            )
        return candidates

    def search(self, *, model_name: str, limit: int, recorder: CallRecorder) -> list[SourceCandidate]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.volc_search_api_key}",
        }
        recorder.check("search")
        with timer() as box:
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        self.endpoint,
                        headers=headers,
                        json=self._build_payload(model_name, limit),
                    )
            except httpx.TimeoutException as exc:
                recorder.record(
                    "search", provider=self.name, duration_ms=box["ms"], ok=False,
                    error_code=ErrorCode.UPSTREAM_TIMEOUT.value,
                )
                raise AppError(ErrorCode.UPSTREAM_TIMEOUT, message="搜图超时，请稍后重试。") from exc
            except httpx.HTTPError as exc:
                recorder.record(
                    "search", provider=self.name, duration_ms=box["ms"], ok=False,
                    error_code=ErrorCode.IMAGE_SEARCH_FAILED.value,
                )
                raise AppError(
                    ErrorCode.IMAGE_SEARCH_FAILED, detail={"reason": type(exc).__name__}
                ) from exc

            if response.status_code >= 400:
                code = {
                    401: ErrorCode.UPSTREAM_AUTH_FAILED,
                    403: ErrorCode.UPSTREAM_AUTH_FAILED,
                    429: ErrorCode.UPSTREAM_RATE_LIMITED,
                }.get(response.status_code, ErrorCode.IMAGE_SEARCH_FAILED)
                recorder.record(
                    "search", provider=self.name, duration_ms=box["ms"], ok=False,
                    error_code=code.value,
                )
                raise AppError(code, detail={"status": response.status_code})
            try:
                data = response.json()
            except ValueError as exc:
                raise AppError(
                    ErrorCode.IMAGE_SEARCH_FAILED, detail={"reason": "非 JSON 响应"}
                ) from exc

        candidates = self._parse_response(data if isinstance(data, dict) else {}, limit)
        recorder.record(
            "search",
            provider=self.name,
            model="doubao-search-custom",
            duration_ms=box["ms"],
            detail={
                "found": len(candidates),
                "clean": sum(1 for c in candidates if getattr(c, "blur", None) == "清晰"),
            },
        )
        return candidates


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
