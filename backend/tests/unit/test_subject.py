"""主体定位（services/cv/subject.py）的单元测试。

用合成图覆盖实测出来的三种情形：
- 详情页式：唯一"像鞋"的主体 → ok
- 列表页式：多个大小相近的主体 → multi
- 找不到：干净页面 → none
外加"白色鞋面漏检"的回归：只框到彩色大底时，应扩展成整只鞋。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from app.services.cv.subject import (
    Subject,
    detect_subjects,
    expand_to_full_subject,
    judge_subjects,
    suggest_crop,
)


def _canvas(width: int = 1200, height: int = 1600) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), "white")
    return image, ImageDraw.Draw(image)


def _shoe_like(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: str) -> None:
    """画一个"像鞋"的色块（宽高比约 2:1）。"""
    draw.ellipse(box, fill=color)


def test_single_subject_is_ok_and_returns_crop() -> None:
    image, draw = _canvas()
    _shoe_like(draw, (200, 400, 900, 750), "#2b3a8f")  # 700×350 ≈ 2:1
    verdict = judge_subjects(np.array(image))

    assert verdict.status == "ok"
    assert verdict.ok
    assert verdict.suggested_crop is not None
    x, y, w, h = verdict.suggested_crop
    assert w > 0 and h > 0
    # 裁切框应覆盖主体并留有余量
    assert x <= 200 and y <= 400
    assert x + w >= 900 and y + h >= 750


def test_multiple_similar_subjects_are_flagged() -> None:
    image, draw = _canvas()
    _shoe_like(draw, (80, 300, 480, 500), "#111111")
    _shoe_like(draw, (620, 300, 1020, 500), "#aa2222")
    _shoe_like(draw, (80, 900, 480, 1100), "#22aa22")
    _shoe_like(draw, (620, 900, 1020, 1100), "#2222aa")

    verdict = judge_subjects(np.array(image))
    assert verdict.status == "multi", "多个大小相近的候选应判为列表页"
    assert len(verdict.subjects) >= 4
    assert verdict.dominant_ratio is not None and verdict.dominant_ratio < 2.0


def test_empty_page_has_no_subject() -> None:
    image, _draw = _canvas()
    verdict = judge_subjects(np.array(image))
    assert verdict.status == "none"
    assert verdict.suggested_crop is None
    assert detect_subjects(np.array(image)) == []


def test_dominant_subject_wins_over_thumbnails() -> None:
    """详情页常见形态：主体很大 + 底部一排小缩略图 → 应判 ok。"""
    image, draw = _canvas()
    _shoe_like(draw, (150, 300, 1050, 750), "#3355cc")   # 主体 900×450
    for i in range(4):
        _shoe_like(draw, (100 + i * 260, 1200, 300 + i * 260, 1300), "#888888")

    verdict = judge_subjects(np.array(image))
    assert verdict.status == "ok"
    assert verdict.dominant_ratio is None or verdict.dominant_ratio >= 2.0


def test_white_upper_is_recovered_by_expansion() -> None:
    """回归：白色鞋面（近背景白）会被"高饱和/暗区"判据漏掉。

    真实案例（得物白鞋截图）：核心候选只盖住了彩色后跟，框出来只有半只鞋。
    这里直接验证扩展算法：给定一个只盖住彩色部分的核心候选，
    应把附近的白色鞋面补回来，使框覆盖整只鞋。
    """
    image, draw = _canvas()
    # 白色鞋身（(252,250,246) 与纯白背景接近，但不是同一个色）
    draw.ellipse((200, 400, 950, 700), fill=(252, 250, 246))
    # 彩色后跟 + 彩色大底（真实截图里就是这部分被检出）
    draw.ellipse((640, 420, 950, 740), fill=(60, 70, 200))
    draw.ellipse((200, 640, 950, 730), fill=(60, 70, 200))

    arr = np.array(image)
    # 模拟"只框到彩色部分"的核心候选
    core = Subject(box=(640, 420, 310, 320), area=310 * 320, aspect_ratio=round(310 / 320, 3))
    grown = expand_to_full_subject(arr, core)

    core_area = core.box[2] * core.box[3]
    grown_area = grown.box[2] * grown.box[3]
    assert grown_area > core_area * 1.05, "扩展后应当变大（把白色鞋面补回来）"
    assert grown.box[0] <= 320, "扩展后应向左覆盖到白色鞋头"


def test_flat_colored_sole_alone_yields_no_candidate() -> None:
    """已知局限（写成测试，避免将来误以为它能行）：

    如果一双白鞋只有"又宽又扁的彩色大底"而没有其他彩色区域，
    宽高比会被"像鞋"规则过滤掉 → 找不到候选（none）。
    此时流程**不拒绝**用户，而是让他手动拖动裁切框（前端已支持）。
    """
    image, draw = _canvas()
    draw.ellipse((200, 400, 950, 700), fill=(253, 251, 247))  # 白鞋身
    draw.ellipse((200, 640, 950, 720), fill=(60, 70, 200))  # 仅一条扁大底 → 宽高比 7.5

    verdict = judge_subjects(np.array(image))
    assert verdict.status == "none"
    assert verdict.ok is False
    # 关键：这种情况不是 multi（不能用"多只鞋"的提示词），前端应引导手动框选
    assert verdict.status != "multi"


def test_suggest_crop_stays_inside_image() -> None:
    subject = Subject(box=(10, 10, 400, 200), area=80000, aspect_ratio=2.0)
    x, y, w, h = suggest_crop((500, 300), subject)
    assert x >= 0 and y >= 0
    assert x + w <= 500 and y + h <= 300
