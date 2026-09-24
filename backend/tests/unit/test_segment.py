"""抠图精修（services/cv/segment.py）的单元测试。

锁住 2026-09-24 修的那个致命问题：**白鞋配白底时，鞋子自己白色的部分被当成背景删掉**。
实测证据：PG4 的掩膜只剩黑勾与红饰片（覆盖 0.135），骨架图因此没有鞋头轮廓，
生成结果是一个楔形；Carmelo 1.5 的白色中底整块消失。
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.services.cv.segment import segment_shoe
from app.services.cv.silhouette import subject_mask_from_cutout


def _png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def _white_shoe_photo() -> bytes:
    """合成一张"白鞋配白底"：鞋身纯白，只有一圈深色轮廓与深色鞋底。

    形状特意做成"空心圆环 + 鞋底"：粗掩膜（与背景色距离 > 40）只会留下这两条深色带，
    白色鞋面完全落在背景色容差内 —— 正是线上 PG4 / Carmelo 1.5 的失败形态。
    """
    image = np.full((400, 600, 3), 255, np.uint8)
    cv2.ellipse(image, (300, 190), (190, 90), 0, 0, 360, (40, 40, 40), 10)
    image[268:290, 130:470] = 60  # 鞋底
    return _png(image)


def _dark_shoe_photo() -> bytes:
    image = np.full((400, 600, 3), 255, np.uint8)
    cv2.ellipse(image, (300, 200), (190, 90), 0, 0, 360, (30, 30, 30), -1)
    return _png(image)


def _alpha_passthrough_photo() -> bytes:
    rgba = Image.new("RGBA", (300, 300), (200, 30, 30, 255))
    mask = Image.new("L", (300, 300), 0)
    ImageDraw.Draw(mask).rectangle([50, 50, 250, 250], fill=255)
    rgba.putalpha(mask)
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    return buffer.getvalue()


def test_alpha_passthrough_keeps_existing_mask() -> None:
    """已经带透明通道的图（如用户自己抠好的 PNG）直接透传，不做任何猜测。"""
    cutout, meta = segment_shoe(_alpha_passthrough_photo())
    assert meta["method"] == "alpha_passthrough"
    mask = subject_mask_from_cutout(cutout)
    assert mask is not None
    assert mask[150, 150]
    assert not mask[10, 10]


def test_white_shoe_keeps_its_white_body() -> None:
    """白鞋的内部必须被保留 —— 原来这里会被删掉，只剩一圈轮廓与鞋底。"""
    cutout, meta = segment_shoe(_white_shoe_photo())
    mask = subject_mask_from_cutout(cutout)
    assert mask is not None
    assert mask[190, 300], "鞋子正中间（白色鞋面）必须算作主体"
    assert float(mask.mean()) > 0.15, "整只鞋的面积远大于一圈细轮廓"
    assert "grabcut" in meta["method"], "这种图必须走精修"


def test_white_shoe_meta_reports_the_gain() -> None:
    _cutout, meta = segment_shoe(_white_shoe_photo())
    assert meta["coarse_keep_ratio"] < meta["keep_ratio"]
    assert meta["refine_gain"] > 0


def test_dark_shoe_still_works() -> None:
    cutout, _meta = segment_shoe(_dark_shoe_photo())
    mask = subject_mask_from_cutout(cutout)
    assert mask is not None
    expected = float(np.pi * 190 * 90 / (400 * 600))
    assert abs(float(mask.mean()) - expected) < 0.05


def test_tiny_subject_falls_back_instead_of_crashing() -> None:
    """主体小到连 GrabCut 都救不回来时，回退原图而不是抛异常。"""
    image = np.full((400, 600, 3), 255, np.uint8)
    image[200:203, 300:303] = 0  # 一个 3x3 的噪点
    cutout, meta = segment_shoe(_png(image))
    assert meta["method"] == "fallback_original", "没找到主体时老老实实回退，别凭空造一个"
    assert subject_mask_from_cutout(cutout) is not None
