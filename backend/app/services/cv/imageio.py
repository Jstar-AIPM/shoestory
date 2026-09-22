"""图像读写与校验：真实内容类型、尺寸、大小限制（工程约定）。"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.core.errors import AppError, ErrorCode

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
MIN_EDGE = 400
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}


def validate_image_bytes(data: bytes, *, min_edge: int = MIN_EDGE, max_bytes: int = MAX_IMAGE_BYTES) -> dict[str, Any]:
    """用 Pillow 真实解码校验（不信任扩展名），拒绝 SVG/HTML 伪装与超大文件。"""
    if not data:
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE, detail={"reason": "空文件"})
    if len(data) > max_bytes:
        raise AppError(
            ErrorCode.UNSUPPORTED_IMAGE,
            message=f"图片太大（超过 {max_bytes // 1024 // 1024}MB），请换一张更小的图。",
        )
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = (img.format or "").upper()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE, detail={"reason": "无法解码"}) from exc
    if fmt not in ALLOWED_FORMATS:
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE, detail={"reason": f"格式 {fmt or '未知'}"})
    if width < min_edge or height < min_edge:
        raise AppError(
            ErrorCode.UNSUPPORTED_IMAGE,
            message=f"图片太小（至少 {min_edge}×{min_edge}px），请换一张更清晰的图。",
            detail={"width": width, "height": height},
        )
    return {"format": fmt, "width": width, "height": height}


def open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE) from exc


def encode_png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def to_rgba(data: bytes) -> Image.Image:
    return open_image(data).convert("RGBA")


def to_rgb_on_white(data: bytes) -> Image.Image:
    img = to_rgba(data)
    canvas = Image.new("RGB", img.size, (255, 255, 255))
    canvas.paste(img, mask=img.split()[-1])
    return canvas


def has_alpha_content(data: bytes) -> bool:
    img = to_rgba(data)
    alpha = img.split()[-1]
    return alpha.getextrema()[0] < 250


def prepare_for_vision(data: bytes, *, max_edge: int = 1024, quality: int = 85) -> bytes:
    """给视觉模型看的缩略图：长边限制 + JPEG 压缩。

    真实踩坑：直接把 1536x1024 的原图/照片（PNG，可达几 MB）传给视觉模型，
    单次质检耗时会长到超时（出图 69s 正常，质检却卡住不返回），而且又贵。
    质检只需要“看得准”，不需要“看得清”——缩到长边 1024 的 JPEG 就够。
    """
    img = to_rgb_on_white(data)
    longest = max(img.size)
    if longest > max_edge:
        scale = max_edge / longest
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
