"""上传图体检接口（V2 输入方式的入口）。

## 为什么用 JSON + base64 而不是 multipart
- 前端本来只走 JSON（`lib/api/client.ts`），用 base64 就不用为上传单开一条路径；
- 少一个依赖（FastAPI 的 multipart 需要 `python-multipart`，线上环境装包不稳）；
- 代价是请求体大 1/3 —— 由**前端先把图压到长边 ≤1600 再上传**来抵消（体积约 200–400KB）。

## 两次调用的分工（成本敏感）
- 第一次（不带 crop）：**只跑 CV**（本机计算），返回"建议裁切框"，前端预填到拖拽框里；
- 第二次（带 crop）：裁切后跑 AI 体检（本机计算），返回三档结论与文案。
这样"用户只是传张图看看"不会产生模型费用。
"""

from __future__ import annotations

import base64
import binascii
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import current_identity, get_container
from app.core.errors import AppError, ErrorCode
from app.services.auth.quota import consume_inspect
from app.services.inspect import InspectResult, inspect_upload
from app.services.providers.base import CallRecorder

router = APIRouter(tags=["inspect"])


class CropBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


class InspectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 图片的 base64（可带 `data:image/jpeg;base64,` 前缀）
    image_base64: str = Field(min_length=32)
    #: 用户确认过的裁切框；不传则只做 CV 定位
    crop: CropBox | None = None


class InspectOut(BaseModel):
    """给前端的体检结果（字段名保持直白，前端只负责渲染）。"""

    ok: bool
    tier: str
    message: str
    hint: str
    crop: CropBox | None
    image: dict
    subject: dict
    detail: dict


def _decode(data: str) -> bytes:
    raw = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        payload = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise AppError(ErrorCode.INVALID_INPUT, detail={"reason": "图片数据不是合法 base64"}) from exc
    if len(payload) < 64:
        raise AppError(ErrorCode.INVALID_INPUT, detail={"reason": "图片数据过短"})
    return payload


def _shrink(data: bytes, max_edge: int) -> bytes:
    """超过 ``max_edge`` 的图等比缩小（保护内存与上游计费；画布只需 1536 宽）。"""
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if max(image.size) <= max_edge:
        return data
    ratio = max_edge / max(image.size)
    resized = image.convert("RGB").resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
    )
    buffer = io.BytesIO()
    resized.save(buffer, "PNG")
    return buffer.getvalue()


def _to_out(result: InspectResult) -> InspectOut:
    crop = None
    if result.crop:
        crop = CropBox(x=result.crop[0], y=result.crop[1], w=result.crop[2], h=result.crop[3])
    vision = result.vision
    return InspectOut(
        ok=result.ok,
        tier=result.tier,
        message=result.message,
        hint=result.hint,
        crop=crop,
        image={"width": result.image_size[0], "height": result.image_size[1]},
        subject={"status": result.subject_status, "count": result.subject_count},
        detail={
            "brand": vision.brand if vision else "",
            "model_name": vision.model_name if vision else "",
            "colorway": vision.colorway if vision else "",
            "display_name": result.display_name,
            "logo_type": result.logo_type,
            "logo_position": vision.logo.position if vision and vision.logo.usable else "",
            "logo_fill_required": vision.logo.fill_required if vision else True,
            "texts": result.texts,
            "text_stamps": [
                {"text": item.text, "position": item.position, "box": list(item.box) if item.box else None}
                for item in (vision.texts if vision else [])
            ],
            "shoe_count": result.subject_count,
            "confidence": vision.confidence if vision else 0.0,
        },
    )


@router.post("/inspect", response_model=InspectOut)
def inspect(
    payload: InspectIn,
    request: Request,
    owner_id: str = Depends(current_identity),
) -> InspectOut:
    """体检一张上传图：能不能画、画哪一块、是什么鞋。"""
    container = get_container(request)
    settings = container.settings

    data = _shrink(_decode(payload.image_base64), settings.max_upload_edge)

    # 只有"用户确认裁切框"这一步才会调用视觉模型 → 此处才计入护栏
    if payload.crop is not None:
        consume_inspect(settings, owner_id, today=date.today().isoformat())

    recorder = CallRecorder(settings.task_max_upstream_calls, settings)
    result = inspect_upload(
        data,
        providers=container.providers,
        recorder=recorder,
        crop=payload.crop.as_tuple() if payload.crop else None,
    )
    return _to_out(result)
