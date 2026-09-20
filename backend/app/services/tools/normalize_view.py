"""工具：校正到 3:2 标准画布（normalize_view）。"""

from __future__ import annotations

from app.services.cv.normalize import normalize_to_canvas


def normalize_view(
    cutout_bytes: bytes, *, width: int, height: int, padding_ratio: float = 0.08
) -> tuple[bytes, dict]:
    return normalize_to_canvas(
        cutout_bytes, width=width, height=height, padding_ratio=padding_ratio
    )
