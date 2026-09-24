"""风格度量的单元测试（services/cv/style.py）。

重点锁住 2026-09-24 新增的 `thick_ink_share`：它承担"这双鞋是不是太轻（没有实色块）"的判断。

为什么不能用原来的 `solid_black_share`：那个指标把所有"面积 ≥2000 的连通域"都算作实心块，
于是一条又粗又长的外轮廓也被算进去，实测分辨不出好坏
（被判"太轻"的 AF1 = 0.062，被评"很好"的 PG5 = 0.041）。
新指标用半径 8px 的开运算抹掉一切宽度不足 16px 的笔画，剩下的只能是真色块。
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png
from app.services.cv.style import measure_style

W, H = 1536, 1024


def _png(array: np.ndarray) -> bytes:
    return encode_png(Image.fromarray(array.astype(np.uint8), mode="L"))


def test_thin_lines_have_no_thick_ink() -> None:
    """纯线描（线宽 3px）：实色块占比必须是 0。"""
    canvas = np.full((H, W), 255, np.uint8)
    canvas[200:203, 100:1400] = 0
    canvas[400:403, 100:1400] = 0
    canvas[600:603, 100:1400] = 0
    metrics = measure_style(_png(canvas))
    assert metrics["thick_ink_share"] == 0.0
    assert metrics["max_stroke_px"] <= 5.0


def test_filled_block_is_measured() -> None:
    """一块 80px 高的实心块：开运算后应当留下来。"""
    canvas = np.full((H, W), 255, np.uint8)
    canvas[300:380, 400:800] = 0  # 80px 高的实心矩形
    metrics = measure_style(_png(canvas))
    assert metrics["thick_ink_share"] > 0.005
    assert metrics["max_stroke_px"] >= 80.0


def test_outline_alone_does_not_count_as_fill() -> None:
    """粗外轮廓（14px，属于正常的线稿语言）不该被当成"实色块"。

    允许极小的残量：开运算在拐角处会留下一点点（实测 0.00014，约 220 像素）。
    但相对真正的填色块（≥0.005）小一个量级以上，所以在阈值上完全分得开。
    """
    canvas = np.full((H, W), 255, np.uint8)
    canvas[200:214, 100:1400] = 0  # 14px 粗线
    canvas[200:600, 100:114] = 0
    metrics = measure_style(_png(canvas))
    assert metrics["thick_ink_share"] <= 0.0005, "14px 的线是轮廓，不是色块"
    assert metrics["solid_black_share"] > 0.0, "旧指标仍会把粗长线算成实心块（所以它不好用）"


def test_thick_ink_distinguishes_light_from_filled() -> None:
    """同一双鞋：纯线描 vs 加一块填色 —— 新指标必须拉开差距。"""
    light = np.full((H, W), 255, np.uint8)
    light[200:203, 100:1400] = 0
    filled = light.copy()
    filled[430:520, 700:1030] = 0  # 一块填实的 Logo

    assert measure_style(_png(light))["thick_ink_share"] == 0.0
    assert measure_style(_png(filled))["thick_ink_share"] > 0.005


def test_empty_image_returns_zeroed_metrics() -> None:
    metrics = measure_style(_png(np.full((H, W), 255, np.uint8)))
    assert metrics["thick_ink_share"] == 0.0
    assert metrics["max_stroke_px"] == 0.0
    assert metrics["ink_ratio"] == 0.0
