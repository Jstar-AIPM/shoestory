"""工具：去背景（segment_shoe）。"""

from __future__ import annotations

from app.services.cv.segment import segment_shoe as _segment_shoe


def segment_shoe(source_bytes: bytes) -> tuple[bytes, dict]:
    return _segment_shoe(source_bytes)
