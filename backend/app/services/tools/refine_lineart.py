"""工具：后处理（refine_lineart）——二值化 + 去噪 + 归一到固定 3:2 白底画布。

为什么必须归一到固定画布：不同模型/版本返回的尺寸不同（例如 Seedream 5.0 pro 用
"分辨率档位"时由模型决定最终像素），而 PRD 要求画稿固定 3:2、白底、纯二值。
"等比缩放 + 白底居中补齐"对白底黑线的画稿是视觉无损的，且让硬指标恒成立。
"""

from __future__ import annotations

from app.services.cv.binarize import refine_lineart as _refine


def refine_lineart(
    raw_bytes: bytes,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> tuple[bytes, dict]:
    return _refine(raw_bytes, target_width=target_width, target_height=target_height)
