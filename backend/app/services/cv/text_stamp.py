"""文字兜底贴合：从原图裁出文字区域、二值化成「白底黑字」、贴到线稿上。

决策记录「V2 输入与风格」七.③ / 九.⑧：
- 图像模型渲染小字不可靠（容易糊/写错）；
- 兜底 = 质检发现文字缺失/乱码时，把原图对应文字区域裁出来、二值化后贴合到线稿
  （确定性做法，可保证文字与实物一致 —— 宁缺勿错）。

坐标链路：体检图（裁切图）→ segment_shoe（尺寸不变）→ normalize_to_canvas（裁主体+等比缩放+居中）。
因此从「体检图坐标」到「画布坐标」是一个仿射变换：
    canvas = (src - subject_bbox.xy) * scale + offset
画布与最终线稿同尺寸（1536x1024），所以画布坐标 == 线稿坐标。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgb_on_white

#: 文字区域里"内容占比"的合法区间（全白/全黑都说明没裁到文字）
MIN_INK_RATIO = 0.003
MAX_INK_RATIO = 0.85


@dataclass(frozen=True)
class TextStamp:
    """一块待贴合的文字（白底黑字二值图 + 其在画布上的位置）。"""

    box: tuple[int, int, int, int]  # 画布坐标 x,y,w,h（已夹取）
    png: bytes  # 二值图，尺寸 = (w, h)，文字为黑(0)


def map_box_to_canvas(
    box_norm: tuple[float, float, float, float],
    *,
    cropped_size: tuple[int, int],
    subject_bbox: tuple[int, int, int, int],
    scale: float,
    offset: tuple[int, int],
) -> tuple[int, int, int, int]:
    """体检图归一化 bbox → 画布坐标 bbox。"""
    cw, ch = cropped_size
    px = box_norm[0] * cw
    py = box_norm[1] * ch
    pw = box_norm[2] * cw
    ph = box_norm[3] * ch
    x = offset[0] + (px - subject_bbox[0]) * scale
    y = offset[1] + (py - subject_bbox[1]) * scale
    return (int(round(x)), int(round(y)), max(1, int(round(pw * scale))), max(1, int(round(ph * scale))))


def _clamp_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return (0, 0, 0, 0)
    return (x0, y0, x1 - x0, y1 - y0)


def extract_text_stamp(canvas_rgb: np.ndarray, box: tuple[int, int, int, int]) -> bytes | None:
    """从画布裁出文字区域，二值化成「白底黑字」。裁不出文字返回 None。"""
    x, y, w, h = box
    if w < 2 or h < 2:
        return None
    region = canvas_rgb[y : y + h, x : x + w]
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    dark_ratio = float((binary == 0).mean())
    # 文字通常是少数类：暗像素少 → 文字为暗；暗像素多 → 深底浅字，文字为亮
    ink = (binary == 0) if dark_ratio <= 0.5 else (binary == 255)
    stamp = np.where(ink, 0, 255).astype(np.uint8)

    ink_ratio = float((stamp == 0).mean())
    if not (MIN_INK_RATIO <= ink_ratio <= MAX_INK_RATIO):
        return None
    return encode_png(Image.fromarray(stamp, mode="L"))


def build_text_stamp(
    canvas_rgb: np.ndarray,
    *,
    box_norm: tuple[float, float, float, float],
    cropped_size: tuple[int, int],
    subject_bbox: tuple[int, int, int, int],
    scale: float,
    offset: tuple[int, int],
) -> TextStamp | None:
    """体检 bbox → 画布 bbox → 裁文字二值图。任一步失败返回 None（兜底不致命）。"""
    height, width = canvas_rgb.shape[:2]
    box = _clamp_box(
        map_box_to_canvas(box_norm, cropped_size=cropped_size, subject_bbox=subject_bbox, scale=scale, offset=offset),
        width,
        height,
    )
    if box[2] == 0 or box[3] == 0:
        return None
    png = extract_text_stamp(canvas_rgb, box)
    if png is None:
        return None
    return TextStamp(box=box, png=png)


def composite_text_stamps(artwork_png: bytes, stamps: list[TextStamp]) -> bytes:
    """把文字贴到线稿上（线稿是白底黑线二值图，文字同样用黑色贴入）。"""
    img = to_rgb_on_white(artwork_png).convert("L")
    arr = np.array(img)
    height, width = arr.shape[:2]

    for stamp in stamps:
        x, y, w, h = stamp.box
        stamp_arr = np.array(Image.open(io.BytesIO(stamp.png)).convert("L"))
        if (stamp_arr.shape[1], stamp_arr.shape[0]) != (w, h):
            stamp_arr = np.array(Image.fromarray(stamp_arr).resize((w, h), Image.LANCZOS))
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        sub = stamp_arr[: y1 - y0, : x1 - x0]
        mask = sub < 128  # 文字 = 黑
        region = arr[y0:y1, x0:x1]
        region[mask] = 0

    return encode_png(Image.fromarray(arr, mode="L"))
