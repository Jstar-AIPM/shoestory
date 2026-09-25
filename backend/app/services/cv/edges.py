"""结构骨架（edge map）：把原鞋的边缘线稿作为**第二张参考图**一起喂给图生图模型。

用意：风格模板里写的是 `structure_control: controlnet_edge`（用边缘引导锁结构）。
火山方舟的图片生成 API 没有直接的 ControlNet 参数，但支持**多参考图**（`image` 传数组）。
因此我们用确定性 CV 抽一张"边缘骨架图"作为额外参考，等效地给模型一个结构约束——
这是"忠于原鞋、不要自由创作"最有效的手段之一（见 PRD 的"忠于原鞋、不要自由创作"要求）。

## 2026-09-24 修正：必须把"鞋的外轮廓"画进去

原来这张骨架图只有 Canny 边缘。Canny 抓的是**颜色突变**，所以当鞋子与背景同为白色时
（PG4 的白鞋面、Stan Smith 的白色中底），**那段轮廓在骨架图上根本不存在**。
模型拿到的是一张"前掌没有边界"的骨架，只能自己编 —— 线上就是这么画出一个楔形的。

修法：把抠图得到的 alpha 掩膜的外轮廓**确定性地画进骨架图**。
掩膜本来就精确知道"鞋在哪里"，只是之前没人拿它去约束生成。另外把 Canny 限制在掩膜内部，
顺带去掉背景里的杂点与阴影边。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgb_on_white
from app.services.cv.silhouette import (
    CANVAS_W,
    SUBJECT_PAD,
    subject_mask_from_canvas,
    subject_mask_on_canvas,
)

MAX_EDGE_PX = 1024

#: 外轮廓线宽（按输出长边等比缩放，保证不同尺寸下观感一致）
CONTOUR_WIDTH_AT_MAX_EDGE = 3


def extract_edge_map(
    canvas_bytes: bytes,
    *,
    cutout_png: bytes | None = None,
    padding_ratio: float = SUBJECT_PAD,
    max_edge: int = MAX_EDGE_PX,
) -> tuple[bytes, dict]:
    """返回 (白底黑线的边缘骨架 PNG, 元信息)。

    ``cutout_png`` 是抠图结果（带 alpha）。给了它就能拿到**精确的外轮廓**；
    没给则退化成从画布按"非白像素"估掩膜（白鞋会漏，所以正常链路一定要传）。
    """
    rgb = to_rgb_on_white(canvas_bytes)
    width, height = rgb.size

    mask: np.ndarray | None = None
    if cutout_png is not None:
        mask = subject_mask_on_canvas(
            cutout_png, width=width, height=height, padding_ratio=padding_ratio
        )
    if mask is None:
        mask = subject_mask_from_canvas(canvas_bytes)

    # 放大一点点再取轮廓：轮廓应当压在鞋的外沿上，而不是切进鞋里
    mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0

    if max(width, height) > max_edge:
        scale = max_edge / max(width, height)
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        rgb = rgb.resize(new_size, Image.LANCZOS)
        mask = cv2.resize(mask.astype(np.uint8), new_size, interpolation=cv2.INTER_NEAREST) > 0

    gray = np.array(rgb.convert("L"))
    # 中值滤波比高斯更适合这里：鞋面的编织纹理会被抹平，而真正的结构边界能保留。
    # 用高斯时纹理会变成一大片密集边缘，聚合后看起来像一块黑斑，容易被模型误读成"这里要涂黑"。
    smoothed = cv2.medianBlur(gray, 5)
    edges = cv2.Canny(smoothed, 60, 160)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)
    edges = cv2.dilate(edges, kernel, iterations=1)
    # 只留主体内部的边缘：背景里的杂点、阴影边、商品页文字都被挡掉
    edges = cv2.bitwise_and(edges, edges, mask=mask.astype(np.uint8) * 255)

    # 确定性外轮廓：这是"白鞋配白底"时唯一能告诉模型"鞋的边界在哪"的东西
    lines = edges
    contours, _ = cv2.findContours(mask.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # 输出已被缩到 max_edge，所以线宽直接按输出像素给即可
    cv2.drawContours(lines, contours, -1, 255, thickness=CONTOUR_WIDTH_AT_MAX_EDGE)

    skeleton = np.where(lines > 0, 0, 255).astype(np.uint8)
    ink_ratio = float((skeleton == 0).mean())
    meta = {
        "size": f"{skeleton.shape[1]}x{skeleton.shape[0]}",
        "ink_ratio": round(ink_ratio, 4),
        "method": "canny(in-mask)+contour+dilate",
        "contour_drawn": True,
        "mask_ratio": round(float(mask.mean()), 4),
    }
    return encode_png(Image.fromarray(skeleton, mode="L")), meta
