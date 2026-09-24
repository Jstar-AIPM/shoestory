"""工具：后处理（refine_lineart）——按**风格**决定怎么规范化画稿。

## 为什么这里要分风格（2026-09-24）

原来这里写死了"二值化 + 归一到白底画布"。那是**黑白线稿风格的要求**，不是管线的固有步骤：
黑白稿要的是"纯二值、无灰阶"，而彩色风格（水彩）要的恰恰相反 —— 一旦走 Otsu 二值化，
颜色会被直接抹平。所以交给风格模板的 `postprocess.binarize` 决定：

- `true`（黑白线稿）：二值化 + 去噪 + 归一到固定 3:2 白底画布（原行为，未改动）
- `false`（水彩等彩色风格）：**只做等比缩放 + 补纸色边**，绝不碰颜色

两种路径的硬指标保持一致：尺寸固定、3:2、居中、四周留白。
"""

from __future__ import annotations

from app.services.cv.binarize import fit_colored_artwork
from app.services.cv.binarize import refine_lineart as _refine
from app.services.style.loader import StyleTemplate


def refine_lineart(
    raw_bytes: bytes,
    *,
    style: StyleTemplate | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
) -> tuple[bytes, dict]:
    """按风格规范化画稿。``style=None`` 时按黑白线稿处理（保持旧调用点的行为）。"""
    if style is not None and not style.binarize and target_width and target_height:
        return fit_colored_artwork(
            raw_bytes,
            target_width=target_width,
            target_height=target_height,
            background=style.canvas_background,
        )
    return _refine(raw_bytes, target_width=target_width, target_height=target_height)
