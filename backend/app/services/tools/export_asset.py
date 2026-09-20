"""工具：导出成品（export_asset）——校验通过才导出（3:2 / 白底 / 纯二值）。"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.cv.binarize import check_artwork


def export_asset(artwork_png: bytes, settings: Settings) -> tuple[bytes, dict]:
    check = check_artwork(artwork_png, settings.artwork_width, settings.artwork_height)
    if not check["ratio_ok"] or not check["binary"] or not check["background_ok"]:
        raise AppError(ErrorCode.ARTWORK_INVALID, detail={"check": check})
    return artwork_png, check
