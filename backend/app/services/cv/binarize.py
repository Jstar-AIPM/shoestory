"""二值化与画稿硬指标检查（确定性代码，不信模型）。

`refine_lineart`：自适应/Otsu 二值化 -> 去小噪点 -> 保证像素只有 0/255。
`check_artwork`：3:2 比例、纯二值、白底占比 —— 画稿是否合格由代码判定。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgb_on_white
MIN_WHITE_RATIO = 0.60
MIN_COMPONENT_AREA = 8  # 小于 8 像素的连通域视为噪点
RATIO_TOLERANCE = 0.01


def refine_lineart(
    data: bytes,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    padding_ratio: float = 0.03,
) -> tuple[bytes, dict]:
    """二值化 + 去噪，**并归一到固定的 3:2 白底画布**。

    为什么必须做这一步：不同上游/不同版本返回的尺寸不一样（例如 Seedream 5.0 pro
    指定分辨率档位时由模型决定最终像素），而 PRD 要求画稿固定 3:2、白底、纯二值。
    这里做“等比缩放 + 白底居中补齐”，保证不管模型返回什么尺寸，硬指标恒成立。
    白底补边对“白底黑线”的画稿是视觉无损的。
    """
    gray = np.array(to_rgb_on_white(data).convert("L"))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    ink = (binary == 0).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    removed = 0
    if num > 1:
        for label in range(1, num):
            if stats[label, cv2.CC_STAT_AREA] < MIN_COMPONENT_AREA:
                ink[labels == label] = 0
                removed += 1

    out = np.where(ink > 0, 0, 255).astype(np.uint8)
    resized = False
    if target_width and target_height and (out.shape[1], out.shape[0]) != (target_width, target_height):
        out = _fit_into_canvas(out, target_width, target_height, padding_ratio)
        resized = True

    meta = {
        "components_removed": removed,
        "white_ratio": round(float((out > 127).mean()), 4),
        "binary": bool(np.all((np.unique(out) == 0) | (np.unique(out) == 255))),
        "normalized_to_canvas": resized,
        "output_size": f"{out.shape[1]}x{out.shape[0]}",
    }
    return encode_png(Image.fromarray(out, mode="L")), meta


def _fit_into_canvas(
    binary: np.ndarray, target_width: int, target_height: int, padding_ratio: float
) -> np.ndarray:
    """等比缩放主体居中放入目标画布，四周补白（并进行一次重二值化）。"""
    source = Image.fromarray(binary, mode="L")
    inner_w = max(1, int(target_width * (1 - 2 * padding_ratio)))
    inner_h = max(1, int(target_height * (1 - 2 * padding_ratio)))
    scale = min(inner_w / source.width, inner_h / source.height)
    new_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    resized = source.resize(new_size, Image.LANCZOS)

    canvas = Image.new("L", (target_width, target_height), 255)
    canvas.paste(resized, ((target_width - new_size[0]) // 2, (target_height - new_size[1]) // 2))

    # 缩放会引入灰阶，重新二值化一次，保证输出只有 0/255
    arr = np.array(canvas)
    _, again = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return again.astype(np.uint8)


def check_artwork(data: bytes, expected_width: int, expected_height: int) -> dict:
    """画稿硬指标：比例 3:2、纯二值、白底。canvas_ratio 分数由此判定。"""
    gray = np.array(to_rgb_on_white(data).convert("L"))
    height, width = gray.shape[:2]
    unique = np.unique(gray)
    binary = bool(np.all((unique == 0) | (unique == 255)))
    white_ratio = float((gray > 127).mean())
    expected_ratio = expected_width / expected_height
    ratio = width / height if height else 0.0
    ratio_ok = abs(ratio - expected_ratio) <= RATIO_TOLERANCE
    size_ok = (width, height) == (expected_width, expected_height)
    background_ok = white_ratio >= MIN_WHITE_RATIO
    return {
        "width": width,
        "height": height,
        "ratio": f"{width}:{height}",
        "ratio_ok": bool(ratio_ok and size_ok),
        "binary": binary,
        "white_ratio": round(white_ratio, 4),
        "background": "white" if background_ok else "other",
        "background_ok": bool(background_ok),
        "canvas_score": 1.0 if (ratio_ok and size_ok and binary and background_ok) else 0.0,
        # 本项目 overlay_text=none，从不叠加文字；目视为验收项 8.6
        "has_text_overlay": False,
    }
