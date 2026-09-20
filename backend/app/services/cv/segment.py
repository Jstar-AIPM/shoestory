"""轻量去背景：边界色估计 + 最大连通域（阶段 1 不引入 rembg，见风险 #3）。

失败不致命：任何异常都回退为“原图 + method=fallback_original”，
由后续“白底归一 + 二值化”兜底，绝不因为抠图失败而中断链路。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgba

MIN_KEEP_RATIO = 0.05  # 主体至少占画面 5%，否则判定抠图失败并回退


def _largest_component(mask: np.ndarray) -> np.ndarray:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = int(np.argmax(areas)) + 1
    return np.where(labels == best, 255, 0).astype(np.uint8)


def segment_shoe(data: bytes) -> tuple[bytes, dict]:
    """返回 (PNG 字节, 元信息)。已有透明通道时直接透传。"""
    img = to_rgba(data)
    alpha = np.array(img.split()[-1])
    if alpha.min() < 250:
        return encode_png(img), {"method": "alpha_passthrough"}

    try:
        rgb = np.array(img.convert("RGB"))
        height, width = rgb.shape[:2]
        border = np.concatenate(
            [
                rgb[0:3, :, :].reshape(-1, 3),
                rgb[-3:, :, :].reshape(-1, 3),
                rgb[:, 0:3, :].reshape(-1, 3),
                rgb[:, -3:, :].reshape(-1, 3),
            ]
        )
        bg = np.median(border, axis=0)
        distance = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
        mask = (distance > 40).astype(np.uint8) * 255
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = _largest_component(mask)
        keep_ratio = float((mask > 0).mean())
        if keep_ratio < MIN_KEEP_RATIO:
            return encode_png(img), {"method": "fallback_original", "reason": "subject_too_small"}
        out = img.copy()
        out.putalpha(Image.fromarray(mask))
        return encode_png(out), {"method": "border_color_threshold", "keep_ratio": round(keep_ratio, 4)}
    except Exception as exc:  # pragma: no cover - 防御性回退
        return encode_png(img), {"method": "fallback_original", "reason": type(exc).__name__}
