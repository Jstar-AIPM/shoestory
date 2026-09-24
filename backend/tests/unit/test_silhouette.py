"""轮廓一致性度量（services/cv/silhouette.py）的单元测试。

这组指标承担一个新职责：**把"轮廓像不像"从视觉模型的主观打分，变成代码能判定的数字**。
起因是 2026-09-24 的产品反馈 —— PG4 那张图的鞋身轮廓整块没还原，
而系统里当时没有任何指标能发现这件事（只有 LLM 给的 `shoe_silhouette_match`）。

测试里刻意覆盖"局部缺失"这类情况：整体 IoU 容易被没出问题的那部分平均掉，
所以真正干活的是**分段（鞋头/中段/后跟）覆盖率**。
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png
from app.services.cv.silhouette import (
    artwork_silhouette,
    compare_silhouette,
    silhouette_metrics,
    subject_mask_from_canvas,
    subject_mask_from_cutout,
)

W, H = 600, 400


def _rgb(array: np.ndarray) -> bytes:
    return encode_png(Image.fromarray(array.astype(np.uint8), mode="RGB"))


def _rgba(array: np.ndarray, alpha: np.ndarray) -> bytes:
    stacked = np.dstack([array.astype(np.uint8), alpha.astype(np.uint8)])
    return encode_png(Image.fromarray(stacked, mode="RGBA"))


def _shoe_mask(width: int = 400, height: int = 160) -> np.ndarray:
    """一个"鞋形"掩膜：一个居中偏左的圆角矩形。"""
    mask = np.zeros((H, W), bool)
    mask[120:120 + height, 100:100 + width] = True
    return mask


def _outline_png(mask: np.ndarray) -> bytes:
    """把掩膜画成"白底黑线"的画稿（轮廓线，内部留白）。"""
    import cv2

    canvas = np.full((H, W), 255, np.uint8)
    contours, _ = cv2.findContours(mask.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(canvas, contours, -1, 0, 3)
    return encode_png(Image.fromarray(canvas, mode="L"))


# --------------------------------------------------------------------------- 掩膜来源


def test_subject_mask_from_cutout_uses_alpha() -> None:
    rgb = np.full((H, W, 3), 255, np.uint8)
    alpha = np.zeros((H, W), np.uint8)
    alpha[:, :200] = 255
    mask = subject_mask_from_cutout(_rgba(rgb, alpha))
    assert mask is not None
    assert mask[:, :200].all()
    assert not mask[:, 210:].any()


def test_subject_mask_from_cutout_returns_none_without_alpha() -> None:
    assert subject_mask_from_cutout(_rgb(np.full((H, W, 3), 255, np.uint8))) is None


def test_subject_mask_from_canvas_finds_non_white() -> None:
    canvas = np.full((H, W, 3), 255, np.uint8)
    canvas[100:300, 50:250] = 10  # 深色主体
    mask = subject_mask_from_canvas(_rgb(canvas))
    assert mask[200, 150]
    assert not mask[10, 10]


def test_artwork_silhouette_fills_outline() -> None:
    """画稿只有轮廓线，填充后内部应当算作"鞋"。"""
    silhouette = artwork_silhouette(_outline_png(_shoe_mask()))
    assert silhouette[200, 300], "轮廓内部应当被填满"
    assert not silhouette[10, 10]


# --------------------------------------------------------------------------- 度量本身


def test_identical_shape_scores_one() -> None:
    mask = _shoe_mask()
    metrics = silhouette_metrics(mask, mask, subject_pad=0.0, artwork_pad=0.0)
    assert metrics["ok"] is True
    assert metrics["iou"] == 1.0
    assert metrics["iou_frame"] == 1.0
    assert metrics["band_iou"] == [1.0, 1.0, 1.0]
    assert metrics["band_iou_frame"] == [1.0, 1.0, 1.0]
    assert metrics["aspect_delta"] == 0.0


def test_missing_toe_is_caught_by_band_coverage() -> None:
    """鞋头（左边一段）缺失 —— 这是 PG4 那次的失败形态，必须被定位出来。

    注意：要拿 `band_iou_frame`（内框坐标系）而不是 `band_iou`（bbox 归一化）。
    后者会把“鞋头整块没画”的形状重新拉伸到与原鞋同宽，反而看不出缺失。
    这里 pad 传 0，是为了让两个坐标系完全对齐，把测试聚焦在分段逻辑本身。
    """
    subject = _shoe_mask()
    artwork = subject.copy()
    artwork[:, :220] = False  # 砍掉左边一大段
    metrics = silhouette_metrics(subject, artwork, subject_pad=0.0, artwork_pad=0.0)
    assert metrics["ok"] is True
    assert metrics["band_iou_frame"][0] < 0.5, "鞋头那一段应当明显偏低"
    assert metrics["band_iou_frame"][-1] > 0.9, "后跟没出问题，不该被牵连"
    assert metrics["aspect_delta"] > 0.3, "缺了一截，长宽比也应该变"


def test_bbox_normalization_alone_would_miss_it() -> None:
    """反向验证：只看 bbox 归一化的 iou 是看不出“整块省略”的 —— 所以才需要内框坐标系。"""
    subject = _shoe_mask()
    artwork = subject.copy()
    artwork[:, :220] = False
    metrics = silhouette_metrics(subject, artwork, subject_pad=0.0, artwork_pad=0.0)
    assert metrics["iou"] > 0.9, "bbox 归一化会把这个形状拉伸回去"
    assert metrics["iou_frame"] < metrics["iou"], "内框坐标系才能如实反映"


def test_compare_silhouette_marks_missing_bands() -> None:
    subject = _shoe_mask()
    artwork = subject.copy()
    artwork[:, :220] = False
    result = compare_silhouette(
        cutout_png=None,
        canvas_png=_rgb(np.where(subject[..., None], 0, 255).repeat(3, axis=2)),
        artwork_png=_outline_png(artwork),
    )
    assert result["ok"] is True
    # 这两个来源的留白比例不同（8% / 3%），所以会出现额外偏移；
    # 断言的是“确实报出了缺口”，而不是具体是哪一段
    assert result["missing_bands"], f"应当报出缺口，实得 {result['band_iou_named']}"


def test_aspect_delta_catches_squashed_drawing() -> None:
    """被压扁的画稿要被发现（bbox 归一化后两张图尺寸相同，长宽比只能在缩放前取）。"""
    subject = _shoe_mask(width=400, height=160)
    squashed = np.zeros((H, W), bool)
    squashed[120:200, 100:500] = True  # 高度只有 80，扁了一半
    metrics = silhouette_metrics(subject, squashed, subject_pad=0.0, artwork_pad=0.0)
    assert metrics["aspect_delta"] > 1.0


def test_empty_mask_is_reported_not_crashed() -> None:
    metrics = silhouette_metrics(np.zeros((H, W), bool), _shoe_mask())
    assert metrics == {"ok": False, "reason": "empty_mask"}
