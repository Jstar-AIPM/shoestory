"""工具：导出成品（export_asset）——校验通过才导出。

⚠️ 校验标准**必须按风格来**（2026-09-24 修）：
原来这里写死了"3:2 / 白底 / **纯二值**"，那是黑白线稿风格的要求。
主风格切成水彩之后，水彩画稿是彩色连续色调，会被这个校验直接拦下 ——
表现是**用户画完根本存不进鞋柜**（线上 E2E 抓到的）。
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.cv.binarize import check_artwork
from app.services.style.loader import StyleTemplate


def export_asset(
    artwork_png: bytes, settings: Settings, style: StyleTemplate | None = None
) -> tuple[bytes, dict]:
    """校验画稿并导出。``style=None`` 时按黑白线稿的旧标准处理（兼容旧调用点）。"""
    require_binary = True if style is None else style.binarize
    check = check_artwork(
        artwork_png,
        settings.artwork_width,
        settings.artwork_height,
        require_binary=require_binary,
        min_background_ratio=0.60 if style is None else style.background_ratio_floor,
        background_label="white" if require_binary else "paper",
    )
    ok = (
        check["ratio_ok"]
        and (check["binary"] or not require_binary)
        and check["background_ok"]
    )
    if not ok:
        raise AppError(ErrorCode.ARTWORK_INVALID, detail={"check": check})
    return artwork_png, check
