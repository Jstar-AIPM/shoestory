"""上传图体检接口（V2 输入方式的入口）。

## 为什么用 JSON + base64 而不是 multipart
- 前端本来只走 JSON（`lib/api/client.ts`），用 base64 就不用为上传单开一条路径；
- 少一个依赖（FastAPI 的 multipart 需要 `python-multipart`，线上环境装包不稳）；
- 代价是请求体大 1/3 —— 由**前端先把图压到长边 ≤1600 再上传**来抵消（体积约 200–400KB）。

## 两次调用的分工（成本敏感）
- 第一次（不带 crop）：**只跑 CV**（本机计算），返回"建议裁切框"，前端预填到拖拽框里；
- 第二次（带 crop）：裁切后跑一次 AI 体检，返回三档结论与文案。
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
from app.services.cv.imageio import encode_png, open_image_upright, scale_box, shrink_pil_with_scale
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


def _to_out(result: InspectResult, *, upscale: float = 1.0) -> InspectOut:
    """
    ``upscale`` 把内部（可能缩小过的）坐标换算回**客户端上传的那张图**的坐标系 ——
    对客户端而言坐标空间永远是它自己发过来的图，服务端缩图是实现细节。
    """
    crop = None
    if result.crop:
        box = scale_box(result.crop, upscale)
        crop = CropBox(x=box[0], y=box[1], w=box[2], h=box[3])
    vision = result.vision
    return InspectOut(
        ok=result.ok,
        tier=result.tier,
        message=result.message,
        hint=result.hint,
        crop=crop,
        image={
            "width": int(round(result.image_size[0] * upscale)),
            "height": int(round(result.image_size[1] * upscale)),
        },
        subject={"status": result.subject_status, "count": result.subject_count},
        detail={
            "brand": vision.brand if vision else "",
            "model_name": vision.model_name if vision else "",
            "colorway": vision.colorway if vision else "",
            "display_name": result.display_name,
            "logo_type": result.logo_type,
            "logo_position": vision.logo.position if vision and vision.logo.usable else "",
            "logo_visibility": vision.logo.visibility if vision else "",
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

    # 先把 EXIF 方向摆正（与浏览器的坐标系一致），再缩图；两者都会改变坐标空间，
    # 所以裁切框要乘同一个系数换算。
    image, ratio = shrink_pil_with_scale(open_image_upright(_decode(payload.image_base64)), settings.max_upload_edge)
    data = encode_png(image)

    # 只有"用户确认裁切框"这一步才会调用视觉模型 → 此处才计入护栏
    if payload.crop is not None:
        consume_inspect(settings, owner_id, today=date.today().isoformat())

    # 客户端的裁切框在**原图**坐标系里；服务端缩过图就要换算到缩图坐标系
    crop = payload.crop.as_tuple() if payload.crop else None
    if crop is not None and ratio != 1.0:
        crop = scale_box(crop, ratio)

    recorder = CallRecorder(settings.task_max_upstream_calls, settings)
    result = inspect_upload(
        data,
        providers=container.providers,
        recorder=recorder,
        crop=crop,
    )
    return _to_out(result, upscale=1.0 / ratio)
