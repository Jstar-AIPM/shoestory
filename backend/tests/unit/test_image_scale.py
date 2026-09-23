"""缩放与坐标换算的单测（V2 上传接口的坐标一致性护栏）。

背景：上传接口会在服务端把超大图缩到 ``max_upload_edge`` 以内（保护内存与上游计费），
但客户端的裁切框坐标是**客户端那张图**的坐标系。缩图后如果不换算坐标，
就会裁到"鞋以外"的地方 —— 这是静默的错误结果（不报错、只是画错鞋），
所以必须有测试锁住：``shrink_image_with_scale`` 的系数 + ``scale_box`` 的换算。
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from app.services.cv.imageio import (
    crop_box,
    open_image,
    open_image_upright,
    scale_box,
    shrink_image,
    shrink_image_with_scale,
)


def _image_bytes(width: int, height: int, box: tuple[int, int, int, int] | None = None) -> bytes:
    """白底 + 一块红色矩形（用来验证"裁的是哪一块"）。"""
    image = Image.new("RGB", (width, height), "white")
    if box:
        x, y, w, h = box
        ImageDraw.Draw(image).rectangle((x, y, x + w, y + h), fill=(220, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_small_image_is_untouched_and_scale_is_one() -> None:
    data = _image_bytes(800, 600)
    out, ratio = shrink_image_with_scale(data, 2400)
    assert ratio == 1.0
    assert out is data, "没超限就不该重新编码（省 CPU，也保证坐标空间不变）"


def test_large_image_shrinks_and_reports_scale() -> None:
    data = _image_bytes(3000, 2000)
    out, ratio = shrink_image_with_scale(data, 2400)
    assert abs(ratio - 0.8) < 1e-9
    assert open_image(out).size == (2400, 1600)


def test_shrink_image_keeps_old_signature() -> None:
    data = _image_bytes(3000, 2000)
    assert open_image(shrink_image(data, 1200)).size == (1200, 800)


# ---------------- EXIF 方向：浏览器会摆正，服务端也必须摆正 ----------------


def _exif_jpeg(width: int, height: int, box: tuple[int, int, int, int], orientation: int = 6) -> bytes:
    """造一张带 EXIF 方向（默认 6 = 需顺时针转 90° 才正）的 JPEG。"""
    image = Image.new("RGB", (width, height), "white")
    x, y, w, h = box
    ImageDraw.Draw(image).rectangle((x, y, x + w, y + h), fill=(220, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def _red_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    arr = np.array(image.convert("RGB")).astype(int)
    mask = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 90)
    ys, xs = np.where(mask)
    assert len(xs) > 0, "测试图里应有红块"
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _assert_red_bbox(image: Image.Image, expected: tuple[int, int, int, int], tol: int = 2) -> None:
    """JPEG 有压缩噪声，红块边界允许 ±2px 的偏差。"""
    actual = _red_bbox(image)
    assert all(abs(a - b) <= tol for a, b in zip(actual, expected)), f"红块位置 {actual}，期望 {expected}"


def test_open_image_upright_applies_exif_orientation() -> None:
    """EXIF 方向必须被应用：尺寸转置、内容也真的转过去了（与浏览器看到的一致）。"""
    data = _exif_jpeg(1200, 800, box=(100, 100, 400, 200))

    assert open_image(data).size == (1200, 800), "Pillow 默认忽略 EXIF（这就是风险来源）"
    _assert_red_bbox(open_image(data), (100, 100, 500, 300))

    upright = open_image_upright(data)
    assert upright.size == (800, 1200), "摆正后尺寸应转置"
    _assert_red_bbox(upright, (500, 100, 700, 500)), "摆正后红块位置必须是浏览器看到的位置"


def test_open_image_upright_keeps_plain_image_untouched() -> None:
    """没有 EXIF 方向的图不应被改变（避免把所有上传都重编码一遍）。"""
    data = _image_bytes(1200, 800, box=(100, 100, 400, 200))
    upright = open_image_upright(data)
    assert upright.size == (1200, 800)
    _assert_red_bbox(upright, (100, 100, 500, 300))


def test_scale_box_round_trip_is_exact_for_integer_scales() -> None:
    box = (900, 500, 800, 400)
    down = scale_box(box, 0.8)
    assert down == (720, 400, 640, 320)
    assert scale_box(down, 1 / 0.8) == box, "缩图坐标乘回去必须回到原框"


def test_scale_box_never_collapses_to_zero() -> None:
    assert scale_box((10, 10, 4, 4), 0.01) == (0, 0, 1, 1)
    assert scale_box((5, 5, 100, 100), 1.0) == (5, 5, 100, 100)


def test_scaled_crop_selects_the_same_region_as_original_crop() -> None:
    """核心断言：在缩图上用换算后的框裁 ≈ 在原图上用原框裁（同一块区域）。"""
    origin = _image_bytes(3000, 2000, box=(1000, 600, 600, 300))
    shrunk, ratio = shrink_image_with_scale(origin, 2400)

    client_box = (900, 500, 800, 400)  # 客户端在原图坐标系里框的（红块在框内居中）
    from_original = np.array(crop_box(open_image(origin), client_box).convert("RGB"))
    from_shrunk = np.array(crop_box(open_image(shrunk), scale_box(client_box, ratio)).convert("RGB"))

    assert from_original.shape[:2] == (400, 800)
    assert from_shrunk.shape[:2] == (320, 640), "缩图后的裁切结果尺寸按比例变小（内容同一块）"
    assert abs(float(from_original.mean()) - float(from_shrunk.mean())) < 2.0

    # 两个结果都应是「白边 + 红心」：证明裁到的确实是客户端框的那一块
    for name, patch in (("原图", from_original), ("缩图", from_shrunk)):
        height, width, _ = patch.shape
        center = patch[height // 2, width // 2]
        corner = patch[2, 2]
        assert center[0] > 180 and center[1] < 80, f"{name}结果中心应是红色，实际 {center}"
        assert corner.min() > 200, f"{name}结果边角应是白色，实际 {corner}"
