"""结构骨架（edge map）：把原鞋的边缘线稿作为**第二张参考图**一起喂给图生图模型。

用意：风格模板里写的是 `structure_control: controlnet_edge`（用边缘引导锁结构）。
火山方舟的图片生成 API 没有直接的 ControlNet 参数，但支持**多参考图**（`image` 传数组）。
因此我们用确定性 CV 抽一张"边缘骨架图"作为额外参考，等效地给模型一个结构约束——
这是"忠于原鞋、不要自由创作"最有效的手段之一（PRD 4.5 / 阶段文档 8.4 的落地）。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgb_on_white

MAX_EDGE_PX = 1024


def extract_edge_map(canvas_bytes: bytes, *, max_edge: int = MAX_EDGE_PX) -> tuple[bytes, dict]:
    """返回 (白底黑线的边缘骨架 PNG, 元信息)。"""
    rgb = to_rgb_on_white(canvas_bytes)
    if max(rgb.size) > max_edge:
        scale = max_edge / max(rgb.size)
        rgb = rgb.resize(
            (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))), Image.LANCZOS
        )

    gray = np.array(rgb.convert("L"))
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 60, 160)
    # 让线条连续、可辨认（模型更容易"看见"结构）
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    edges = cv2.dilate(edges, kernel, iterations=1)
    skeleton = np.where(edges > 0, 0, 255).astype(np.uint8)

    ink_ratio = float((skeleton == 0).mean())
    meta = {
        "size": f"{skeleton.shape[1]}x{skeleton.shape[0]}",
        "ink_ratio": round(ink_ratio, 4),
        "method": "canny+close+dilate",
    }
    return encode_png(Image.fromarray(skeleton, mode="L")), meta
