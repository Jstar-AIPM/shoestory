"""彩色画稿的确定性度量（2026-09-24 新增，配合水彩风格）。

## 为什么黑白那套指标不能复用

`cv/style.py` 量的是"墨量、线宽、排线、实心块"—— 那是**纯二值**风格的语言。
彩色画稿里没有黑墨，这些指标要么没有意义，要么（更糟）给出噪声值：
实测轮廓度量在彩色稿上会从 0.03 掉到 0.67 那一档的噪声，把每张水彩都误判成"轮廓塌陷"。

## 这里量什么（每一条都对应风格说明里的硬要求）

| 指标 | 对应风格里的哪句话 |
| --- | --- |
| `subject_ratio` | "鞋子完整进入画面 + 保持大量留白" |
| `paper_luminance` | "使用暖白 / 米白水彩纸背景" |
| `hue_match` | "**配色必须参考原鞋**：保留主色/辅色/点缀色与位置关系" |
| `sat_ratio` | "适度降低饱和度，但不能淡到失去原本颜色的识别度" |
| `chromatic_ratio` | "不要强制把所有鞋都统一成灰调或极淡色" |

`hue_match` 用**色相直方图的重叠度**（只看有颜色的像素），刻意用色相而不是 RGB 距离：
色相基本不受曝光与光照影响，而水彩本来就会"柔化颜色"，用 RGB 距离会把正确的柔化当成错误。
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import to_rgb_on_white
from app.services.cv.silhouette import (
    CANVAS_H,
    CANVAS_W,
    SUBJECT_PAD,
    artwork_silhouette,
    subject_mask_from_canvas,
    subject_mask_on_canvas,
)

#: 色相直方图的桶数（360 / 36 = 每桶 10°）
HUE_BINS = 36
#: 饱和度超过它才算"有颜色的像素"。太低会把纸纹噪声也算进来
CHROMATIC_MIN_SAT = 60
#: 亮点/暗点（V 太极端）的色相不稳定，排除
VALUE_RANGE = (40, 245)


def _hsv_of(data: bytes) -> np.ndarray:
    return cv2.cvtColor(np.array(to_rgb_on_white(data).convert("RGB")), cv2.COLOR_RGB2HSV)


def _chromatic(hsv: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """有颜色的像素：饱和够高、明度不极端。"""
    saturation = hsv[..., 1].astype(np.int32)
    value = hsv[..., 2].astype(np.int32)
    return mask & (saturation >= CHROMATIC_MIN_SAT) & (value >= VALUE_RANGE[0]) & (value <= VALUE_RANGE[1])


def _hue_histogram(hsv: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """按饱和度加权的色相直方图（归一化）。没有足够彩色像素时返回 None。"""
    selected = _chromatic(hsv, mask)
    if selected.sum() < 200:
        return None
    hue = hsv[..., 0][selected].astype(np.int32) * HUE_BINS // 180  # OpenCV 的 H 是 0–179
    weights = hsv[..., 1][selected].astype(np.float64)
    histogram, _ = np.histogram(hue, bins=HUE_BINS, range=(0, HUE_BINS), weights=weights)
    total = histogram.sum()
    return histogram / total if total > 0 else None


def _hue_match(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    """两个色相直方图的重叠度：1 = 完全一致（直方图取交集之和）。

    这正是"配色有没有跑偏"的直接度量 —— 原鞋的主色若被换掉，重叠度会立刻掉下来。
    """
    if a is None or b is None:
        return None
    return round(float(np.minimum(a, b).sum()), 4)


def _mean_saturation(hsv: np.ndarray, mask: np.ndarray) -> float:
    selected = _chromatic(hsv, mask)
    if selected.sum() < 50:
        return 0.0
    return float(hsv[..., 1][selected].mean())


def _paper_color(artwork_png: bytes) -> np.ndarray:
    rgb = np.array(to_rgb_on_white(artwork_png).convert("RGB"))
    border = np.concatenate(
        [
            rgb[0:3, :, :].reshape(-1, 3),
            rgb[-3:, :, :].reshape(-1, 3),
            rgb[:, 0:3, :].reshape(-1, 3),
            rgb[:, -3:, :].reshape(-1, 3),
        ]
    )
    return np.median(border, axis=0)


def measure_color(
    artwork_png: bytes,
    *,
    canvas_png: bytes | None = None,
    cutout_png: bytes | None = None,
) -> dict:
    """对彩色画稿算一组确定性指标。没有原鞋参考时只算与画面自身有关的几项。"""
    artwork_hsv = _hsv_of(artwork_png)
    height, width = artwork_hsv.shape[:2]
    subject = artwork_silhouette(artwork_png, from_background=True)

    metrics: dict = {
        "subject_ratio": round(float(subject.mean()), 4),
        "canvas_size": f"{width}x{height}",
    }

    paper = _paper_color(artwork_png)
    metrics["paper_luminance"] = round(
        float(0.299 * paper[0] + 0.587 * paper[1] + 0.114 * paper[2]), 1
    )

    artwork_hist = _hue_histogram(artwork_hsv, subject)
    metrics["chromatic_ratio"] = round(float(_chromatic(artwork_hsv, subject).sum()) / max(1, int(subject.sum())), 4)

    if canvas_png is not None:
        source_mask = (
            subject_mask_on_canvas(cutout_png, width=width, height=height, padding_ratio=SUBJECT_PAD)
            if cutout_png
            else None
        )
        if source_mask is None:
            source_mask = subject_mask_from_canvas(canvas_png)
        source_hsv = _hsv_of(canvas_png)
        if source_hsv.shape[:2] != (height, width):
            source_hsv = cv2.resize(source_hsv, (width, height), interpolation=cv2.INTER_NEAREST)
            source_mask = cv2.resize(
                source_mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST
            ) > 0

        source_hist = _hue_histogram(source_hsv, source_mask)
        metrics["source_chromatic_ratio"] = round(
            float(_chromatic(source_hsv, source_mask).sum()) / max(1, int(source_mask.sum())), 4
        )
        match = _hue_match(source_hist, artwork_hist)
        # 原鞋本身就是黑白/极浅色时，"色相"这件事没有意义 —— 不参与判定（返回 None）
        metrics["hue_match"] = match

        source_sat = _mean_saturation(source_hsv, source_mask)
        artwork_sat = _mean_saturation(artwork_hsv, subject)
        metrics["sat_ratio"] = (
            round(artwork_sat / source_sat, 3) if source_sat >= 1.0 else None
        )
        metrics["source_saturation"] = round(source_sat, 1)
        metrics["artwork_saturation"] = round(artwork_sat, 1)
    else:
        metrics["hue_match"] = None
        metrics["sat_ratio"] = None

    return metrics


def palette_preview(artwork_png: bytes, *, count: int = 5) -> list[tuple[int, int, int]]:
    """取得主体区域的主要颜色（排查用，不参与判定）。"""
    rgb = np.array(to_rgb_on_white(artwork_png).convert("RGB"))
    mask = artwork_silhouette(artwork_png, from_background=True)
    if mask.sum() < 100:
        return []
    pixels = rgb[mask].reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _compactness, labels, centers = cv2.kmeans(
        pixels, count, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    counts = np.bincount(labels.flatten(), minlength=count)
    order = np.argsort(-counts)
    return [tuple(int(v) for v in centers[i]) for i in order]


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(__import__("io").BytesIO(data)) as img:
        return img.size


__all__ = [
    "CANVAS_H",
    "CANVAS_W",
    "measure_color",
    "palette_preview",
    "image_size",
]
