"""文字兜底贴合（services/cv/text_stamp.py）的单元测试。

覆盖：体检 bbox → 画布坐标映射、裁文字二值化（深底浅字 / 浅底深字）、贴合到线稿。
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png
from app.services.cv.text_stamp import (
    TextStamp,
    composite_text_stamps,
    extract_text_stamp,
    map_box_to_canvas,
)


def _png(arr: np.ndarray) -> bytes:
    return encode_png(Image.fromarray(arr.astype(np.uint8), mode="L"))


def test_map_box_to_canvas_affine() -> None:
    result = map_box_to_canvas(
        (0.5, 0.5, 0.2, 0.1),
        cropped_size=(100, 100),
        subject_bbox=(10, 10, 90, 90),
        scale=0.5,
        offset=(100, 50),
    )
    # px=50, py=50, pw=20, ph=10 → canvas=(100+(50-10)*0.5, 50+(50-10)*0.5, 10, 5)
    assert result == (120, 70, 10, 5)


def test_extract_dark_text_on_light() -> None:
    region = np.full((40, 120, 3), 255, np.uint8)
    region[10:30, 50:70] = 0  # 黑"文字"
    png = extract_text_stamp(region, (0, 0, 120, 40))
    assert png is not None
    stamp = np.array(Image.open(io.BytesIO(png)))
    assert (stamp[15:25, 55:65] == 0).all(), "文字应被二值化成黑色"
    assert (stamp[0:5, 0:5] == 255).all(), "背景应为白色"


def test_extract_light_text_on_dark() -> None:
    region = np.zeros((40, 120, 3), np.uint8)  # 全黑底
    region[10:30, 50:70] = 255  # 白"文字"
    png = extract_text_stamp(region, (0, 0, 120, 40))
    assert png is not None
    stamp = np.array(Image.open(io.BytesIO(png)))
    assert (stamp[15:25, 55:65] == 0).all(), "深底浅字也应把文字转成黑色"


def test_extract_blank_region_returns_none() -> None:
    region = np.full((40, 120, 3), 255, np.uint8)
    assert extract_text_stamp(region, (0, 0, 120, 40)) is None


def test_composite_pastes_text_onto_artwork() -> None:
    artwork = np.full((60, 120), 255, np.uint8)
    stamp = np.full((20, 30), 255, np.uint8)
    stamp[5:15, 5:25] = 0  # 黑块
    ts = TextStamp(box=(10, 10, 30, 20), png=_png(stamp))

    out = composite_text_stamps(_png(artwork), [ts])
    arr = np.array(Image.open(io.BytesIO(out)))

    # 画稿在画布 (10,10) 起贴入 30x20 的贴片，其中 (5,5)-(25,15) 是黑块
    assert (arr[15:25, 15:35] == 0).all(), "文字应贴到画稿上"
    assert (arr[0:5, 0:5] == 255).all(), "未覆盖区域仍是白色"
