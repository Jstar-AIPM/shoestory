"""上传图体检编排：裁切 → CV 主体判定 → AI 体检 → 三档结论 + 给用户的文案。

## 为什么要编排（而不是在接口里堆逻辑）
这个流程有三个"会互相打架"的判断，必须在一处定清楚：
1. **CV 看原图**：框里有几只鞋（列表页要提示用户裁切）；
2. **CV 看裁切图**：裁切后是不是只剩一只；
3. **AI 看裁切图**：到底是不是鞋、是什么鞋、Logo 与文字。

判定顺序与取舍（2026-09-22 与产品经理对齐）：
- "明确不是鞋" → **拒绝**（避免硬画出一堆怪线）：文案要说出"我看到的更像什么"；
- "不确定" → **放行 + 软提示**：拒绝太严比选错更伤体验（V1 的教训）；
- "框里多只鞋" → 提示**重新框选**（不是拒绝：用户拖一下就好）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from app.core.errors import AppError, ErrorCode
from app.schemas.inspect import PhotoInspectOut
from app.services.cv.imageio import validate_image_bytes
from app.services.cv.subject import SubjectVerdict, judge_subjects, suggest_crop
from app.services.providers.base import ProviderBundle

#: 三档结论（前端据此渲染不同提示）
TIER_OK = "ok"
TIER_NOT_SHOE = "not_shoe"
TIER_MULTI = "multi"
TIER_UNCERTAIN = "uncertain"


@dataclass
class InspectResult:
    """体检结果：能不能画 + 为什么 + 下一步怎么办 + 绘制所需信息。"""

    tier: str
    message: str
    hint: str = ""
    crop: tuple[int, int, int, int] | None = None  # 原图坐标 x,y,w,h
    image_size: tuple[int, int] = (0, 0)
    subject_status: str = "ok"
    subject_count: int = 0
    vision: PhotoInspectOut | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """是否允许进入生成（不确定也放行）。"""
        return self.tier in {TIER_OK, TIER_UNCERTAIN}

    @property
    def display_name(self) -> str:
        return self.vision.display_name if self.vision else ""

    @property
    def logo_type(self) -> str:
        return self.vision.logo.type if self.vision and self.vision.logo.usable else ""

    @property
    def texts(self) -> list[str]:
        return self.vision.drawable_texts if self.vision else []


def _crop_image(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image.width, x + w), min(image.height, y + h)
    if x1 - x0 < 32 or y1 - y0 < 32:
        raise AppError(ErrorCode.INVALID_INPUT, detail={"reason": "裁切范围太小"})
    return image.crop((x0, y0, x1, y1))


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def inspect_upload(
    data: bytes,
    *,
    providers: ProviderBundle,
    recorder,
    crop: tuple[int, int, int, int] | None = None,
) -> InspectResult:
    """对用户上传的图做体检。``crop`` 为 None 时先给建议框，不调用 AI。"""
    validate_image_bytes(data)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    full = np.array(image)
    size = (image.width, image.height)

    # ---------- 用户还没框选：只做 CV，返回建议框 ----------
    if crop is None:
        verdict: SubjectVerdict = judge_subjects(full)
        if verdict.status == "multi":
            return InspectResult(
                tier=TIER_MULTI,
                message="这张图里有好几双鞋，我不确定您想画哪一双。",
                hint="把方框拖到只包住您要的那一双，就好了。",
                crop=verdict.suggested_crop,
                image_size=size,
                subject_status=verdict.status,
                subject_count=len(verdict.subjects),
            )
        return InspectResult(
            tier=TIER_OK,
            message="已经帮您框出这双鞋，可以直接开始画。",
            hint="如果框得不准，您可以拖动方框调整一下。",
            crop=verdict.suggested_crop,
            image_size=size,
            subject_status=verdict.status,
            subject_count=len(verdict.subjects),
        )

    # ---------- 用户已框选：判定裁切后的主体 + AI 体检 ----------
    cropped = _crop_image(image, crop)
    cropped_array = np.array(cropped)
    crop_verdict = judge_subjects(cropped_array)

    if crop_verdict.status == "multi":
        return InspectResult(
            tier=TIER_MULTI,
            message="这个框里还是有不止一双鞋，我分不清您想画哪一双。",
            hint="再收一收方框，只留下您要的那一双。",
            crop=crop,
            image_size=size,
            subject_status=crop_verdict.status,
            subject_count=len(crop_verdict.subjects),
        )

    vision = providers.judge.inspect_photo(image=_png_bytes(cropped), recorder=recorder)
    result = InspectResult(
        tier=TIER_OK,
        message="",
        crop=crop,
        image_size=size,
        subject_status=crop_verdict.status,
        subject_count=max(len(crop_verdict.subjects), vision.shoe_count),
        vision=vision,
        extra={"logo": vision.logo.model_dump(), "texts": [t.model_dump() for t in vision.texts]},
    )

    if vision.tier == "not_shoe":
        what = vision.subject_description or "别的东西"
        result.tier = TIER_NOT_SHOE
        result.message = f"看起来这张图里不是运动鞋 —— 我看到的更像「{what}」。"
        result.hint = "这个工具专门把球鞋画成黑白线稿。您可以换一张球鞋的侧面图（白底商品图最好），我马上就能画。"
        return result

    if vision.tier == "uncertain":
        result.tier = TIER_UNCERTAIN
        result.message = "我不太确定这是不是一双球鞋 —— 先按您说的画。"
        result.hint = "如果结果不对，换一张更清晰的侧面图会好很多。"
        return result

    # 明确是鞋
    named = vision.display_name
    result.message = f"认出来了：{named}。" if named else "已经认出这双鞋，可以开始画了。"
    result.hint = "您确认没问题就点「开始画」；也可以重新上传换一张图。"
    if vision.shoe_count > 1:
        result.tier = TIER_MULTI
        result.message = f"这个框里像是还有 {vision.shoe_count} 只鞋。"
        result.hint = "再收一收方框，只留下您要的那一双。"
    return result


def suggest_box_only(data: bytes) -> tuple[tuple[int, int, int, int] | None, tuple[int, int]]:
    """只做 CV 定位（不花钱、不调 AI）：给前端一个"建议裁切框"。"""
    validate_image_bytes(data)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    verdict = judge_subjects(np.array(image))
    if verdict.suggested_crop:
        return verdict.suggested_crop, (image.width, image.height)
    return suggest_crop((image.width, image.height), verdict.subjects[0]) if verdict.subjects else None, (
        image.width,
        image.height,
    )
