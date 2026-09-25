"""风格驱动的后处理与判定（2026-09-24 新增水彩风格时立的规矩）。

## 为什么要有这组测试

原来整条链路写死了"黑白二值"：后处理 Otsu 二值化、画布检查要求纯二值 + 白底、
轮廓度量靠"找黑墨"。这些在黑白线稿上是对的，但**加到彩色风格上会连环出错**：

- 二值化把水彩的颜色直接抹平（画稿废掉）；
- 画布检查判"不是纯二值" → `canvas_score = 0` → 全盘不合格；
- 轮廓度量找不到黑墨 → IoU 掉到 0.03–0.67 → 每张都被误判"轮廓塌陷"、白白重画一次。

所以规矩是：**"要不要二值化、要不要骨架参考、指标怎么算"都由风格决定，不是管线固有步骤。**
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.core.config import STYLES_DIR
from app.services.cv.binarize import check_artwork, fit_colored_artwork
from app.services.cv.imageio import encode_png
from app.services.cv.silhouette import artwork_silhouette, compare_silhouette
from app.services.style.registry import StyleRegistry
from app.services.tools.refine_lineart import refine_lineart

W, H = 1536, 1024
PAPER = (250, 246, 240)


def _paper_canvas_with_shoe() -> bytes:
    """造一张"暖白纸底 + 一块浅色鞋形"的图，模拟水彩产出。

    鞋身特意做成**浅色**（亮度 > 128）—— 真实的水彩产出就是这样（白鞋、浅灰底），
    而这正是"靠灰度<128 找黑墨"那套取法会失效的原因：它几乎什么都找不到。
    """
    canvas = np.full((H, W, 3), PAPER, np.uint8)
    canvas[300:720, 200:1300] = (205, 210, 222)  # 浅蓝灰鞋身
    canvas[620:700, 200:1300] = (232, 234, 238)  # 更浅的中底
    return encode_png(Image.fromarray(canvas, mode="RGB"))


def _styles() -> StyleRegistry:
    return StyleRegistry(STYLES_DIR)


# --------------------------------------------------------------------------- 风格属性


def test_bw_style_keeps_binary_and_structure_reference() -> None:
    style = _styles().get("bw_lineart")
    assert style.binarize is True
    assert style.canvas_background == "#ffffff"
    assert style.needs_structure_reference is True, "黑白稿要骨架图锁结构"
    assert style.background_ratio_floor == 0.60


def test_watercolor_style_is_not_binary_and_skips_structure_reference() -> None:
    style = _styles().get("watercolor")
    assert style.binarize is False, "彩色风格绝不能走二值化"
    assert style.canvas_background == "#faf6f0", "实测纸色 RGB(250,246,240)"
    assert style.needs_structure_reference is False, "骨架图是黑线，喂进去会诱导勾线"
    assert style.background_ratio_floor < 0.60


# --------------------------------------------------------------------------- 后处理分派


def test_colored_postprocess_keeps_colors() -> None:
    """彩色画稿过一遍后处理，颜色必须还在 —— 这是二值化会毁掉的东西。"""
    art, meta = fit_colored_artwork(_paper_canvas_with_shoe(), target_width=W, target_height=H)
    image = Image.open(io.BytesIO(art)).convert("RGB")
    assert image.size == (W, H)
    assert meta["binarized"] is False
    colors = np.unique(np.array(image).reshape(-1, 3), axis=0)
    assert len(colors) > 20, "水彩是连续色调；二值化后会只剩 1–2 种颜色"


def test_colored_postprocess_pads_with_the_configured_background() -> None:
    art, _meta = fit_colored_artwork(
        _paper_canvas_with_shoe(), target_width=W, target_height=H, background="#faf6f0"
    )
    corner = Image.open(io.BytesIO(art)).convert("RGB").getpixel((3, 3))
    assert all(abs(a - b) <= 2 for a, b in zip(corner, PAPER)), corner


def test_refine_lineart_dispatches_by_style() -> None:
    """同一个入口：黑白风格出纯二值，水彩风格保留颜色。"""
    raw = _paper_canvas_with_shoe()
    styles = _styles()
    bw, bw_meta = refine_lineart(raw, style=styles.get("bw_lineart"), target_width=W, target_height=H)
    wc, wc_meta = refine_lineart(raw, style=styles.get("watercolor"), target_width=W, target_height=H)

    bw_colors = set(np.unique(np.array(Image.open(io.BytesIO(bw)).convert("L"))).tolist())
    assert bw_colors <= {0, 255}, "黑白风格必须只剩 0/255"
    assert bw_meta["binary"] is True
    wc_colors = np.unique(np.array(Image.open(io.BytesIO(wc)).convert("RGB")).reshape(-1, 3), axis=0)
    assert len(wc_colors) > 20, f"水彩风格必须保留颜色，实得 {len(wc_colors)} 种"
    assert wc_meta["binarized"] is False


def test_refine_lineart_without_style_keeps_old_behavior() -> None:
    """不传风格时按黑白处理 —— 保证旧调用点与旧测试不受影响。"""
    refined, meta = refine_lineart(_paper_canvas_with_shoe(), target_width=W, target_height=H)
    assert set(np.unique(np.array(Image.open(io.BytesIO(refined)).convert("L"))).tolist()) <= {0, 255}
    assert meta["binary"] is True


# --------------------------------------------------------------------------- 画布检查


def test_canvas_check_rejects_color_when_binary_required() -> None:
    check = check_artwork(_paper_canvas_with_shoe(), W, H, require_binary=True)
    assert check["canvas_score"] == 0.0, "黑白风格下彩色画稿就是不合格"


def test_canvas_check_accepts_color_when_binary_not_required() -> None:
    check = check_artwork(
        _paper_canvas_with_shoe(), W, H, require_binary=False, min_background_ratio=0.45
    )
    assert check["canvas_score"] == 1.0
    assert check["background"] == "white"
    assert check["background_ratio"] > 0.45


def test_canvas_check_still_requires_background_whitespace() -> None:
    """整片糊满颜色（没有留白）在彩色风格下也要判不合格。"""
    canvas = np.full((H, W, 3), (40, 70, 140), np.uint8)
    check = check_artwork(encode_png(Image.fromarray(canvas, "RGB")), W, H, require_binary=False)
    assert check["canvas_score"] == 0.0


# --------------------------------------------------------------------------- 轮廓度量


def test_colored_silhouette_is_taken_from_background_not_black_ink() -> None:
    """彩色画稿里没有黑墨 —— 必须用"与纸色不同"取主体，否则指标完全失效。"""
    art = _paper_canvas_with_shoe()
    from_ink = artwork_silhouette(art, from_background=False).sum()
    from_paper = artwork_silhouette(art, from_background=True).sum()
    assert from_paper > from_ink * 5, f"纸色取法应覆盖整只鞋：{from_paper} vs 黑墨取法 {from_ink}"


def test_silhouette_comparison_uses_the_right_mode() -> None:
    """同一张水彩画稿：用错取法 → IoU 崩；用对取法 → 正常。"""
    canvas = _paper_canvas_with_shoe()
    # 抠图掩膜：与原图主体大致同位置，留一点自然偏差
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[300:720, 220:1280] = (205, 210, 222, 255)
    cutout = encode_png(Image.fromarray(rgba, mode="RGBA"))

    wrong = compare_silhouette(cutout_png=cutout, canvas_png=canvas, artwork_png=canvas,
                               from_background=False)
    right = compare_silhouette(cutout_png=cutout, canvas_png=canvas, artwork_png=canvas,
                               from_background=True)

    # 关键差别：浅色水彩画稿里**没有黑墨**，黑墨取法连主体都抽不出来（ok=False），
    # 于是 IoU 要么算不出来、要么是噪声值 —— 实测线上就是它把每张水彩都误判成
    # "轮廓塌陷"并白白重画一次。纸色取法才能给出有意义的数字。
    # （真实数据的标定值：8 张水彩 0.67–0.93，见 ·质量评测/watercolor-probe）
    assert wrong.get("ok") is False, "浅色画稿用黑墨取法应当抽不到主体"
    assert right["ok"] is True
    assert 0.3 < right["iou_frame"] < 1.0


# --------------------------------------------------------------------------- 导出/归档


def test_export_rejects_color_when_style_is_binary() -> None:
    """黑白风格下，彩色画稿必须被拦下（旧行为，不能退化）。"""
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.services.tools.export_asset import export_asset

    style = _styles().get("bw_lineart")
    settings = Settings(_env_file=None, data_dir="/tmp/x")
    with pytest.raises(AppError):
        export_asset(_paper_canvas_with_shoe(), settings, style)


def test_export_accepts_color_for_watercolor_style() -> None:
    """**线上 E2E 抓到的 bug**：校验标准写死了"纯二值"，导致水彩稿在归档时被拦下 ——
    表现是"用户画完根本存不进鞋柜"。校验必须按风格来。"""
    from app.core.config import Settings
    from app.services.tools.export_asset import export_asset

    style = _styles().get("watercolor")
    settings = Settings(_env_file=None, data_dir="/tmp/x")
    _png, check = export_asset(_paper_canvas_with_shoe(), settings, style)
    assert check["require_binary"] is False
    assert check["background"] == "paper"
    assert check["background_ok"] is True


def test_export_without_style_keeps_old_strictness() -> None:
    """不传风格时按黑白旧标准（兼容旧调用点）。"""
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.services.tools.export_asset import export_asset

    settings = Settings(_env_file=None, data_dir="/tmp/x")
    with pytest.raises(AppError):
        export_asset(_paper_canvas_with_shoe(), settings)
