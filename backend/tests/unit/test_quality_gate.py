"""质检判定（确定性代码）：画布硬指标、Logo 硬门槛、阈值边界。"""

from __future__ import annotations

import io

from PIL import Image

from app.core.config import STYLES_DIR, Settings
from app.schemas.llm import QualityReportOut
from app.services.cv.binarize import check_artwork, refine_lineart
from app.services.style.registry import StyleRegistry
from app.services.tools.verify_lineart import score_and_gate


def png_bytes(width: int, height: int, *, mode: str = "L", value: int = 255) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), value if mode == "L" else (value, value, value)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def default_style():
    return StyleRegistry(STYLES_DIR).get("bw_lineart")


def report(silhouette: float, logo: float, style: float, noise: float) -> QualityReportOut:
    return QualityReportOut(
        shoe_silhouette_match=silhouette,
        logo_legibility=logo,
        style_consistency=style,
        noise_level=noise,
    )


def test_canvas_check_accepts_3_2() -> None:
    check = check_artwork(png_bytes(1536, 1024), 1536, 1024)
    assert check["ratio_ok"] is True
    assert check["binary"] is True
    assert check["background"] == "white"
    assert check["canvas_score"] == 1.0


def test_canvas_check_rejects_wrong_size_and_ratio() -> None:
    check = check_artwork(png_bytes(1500, 1024), 1536, 1024)
    assert check["ratio_ok"] is False
    assert check["canvas_score"] == 0.0


def test_canvas_check_rejects_grayscale_pixels() -> None:
    image = Image.new("L", (1536, 1024), 255)
    for x in range(0, 300):
        for y in range(0, 300):
            image.putpixel((x, y), 128)  # 灰阶：违反“纯二值”
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    check = check_artwork(buffer.getvalue(), 1536, 1024)
    assert check["binary"] is False
    assert check["canvas_score"] == 0.0


def test_refine_lineart_produces_pure_binary() -> None:
    image = Image.new("L", (600, 400), 255)
    for x in range(100, 500):
        image.putpixel((x, 200), 120)  # 灰色线条 -> 应被二值化
    for x in range(100, 102):
        for y in range(300, 302):
            image.putpixel((x, y), 0)  # 2x2 小块噪点 -> 应被清理
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    refined, meta = refine_lineart(buffer.getvalue())
    check = check_artwork(refined, 600, 400)
    assert check["binary"] is True
    assert meta["binary"] is True
    assert meta["components_removed"] >= 1


def test_logo_hard_gate_blocks_high_total_score() -> None:
    style = default_style()
    score, passed, issues = score_and_gate(report(1.0, 0.5, 1.0, 1.0), 1.0, style, 0.80)
    assert score >= 0.80
    assert passed is False
    assert any("logo_legibility" in issue for issue in issues)


def test_canvas_zero_blocks_even_with_perfect_content() -> None:
    style = default_style()
    _score, passed, issues = score_and_gate(report(1.0, 1.0, 1.0, 1.0), 0.0, style, 0.80)
    assert passed is False
    assert any("canvas_ratio" in issue for issue in issues)


def test_threshold_boundary_just_above_min_score_passes() -> None:
    style = default_style()
    # 0.4286*0.35 + 1*0.25 + 1*0.2 + 1*0.1 + 1*0.1 = 0.80001 >= 0.80
    score, passed, _issues = score_and_gate(report(0.4286, 1.0, 1.0, 1.0), 1.0, style, 0.80)
    assert score >= 0.80
    assert passed is True


def test_just_below_threshold_fails() -> None:
    style = default_style()
    _score, passed, issues = score_and_gate(report(0.4, 1.0, 1.0, 1.0), 1.0, style, 0.80)
    assert passed is False
    assert any("低于阈值" in issue for issue in issues)


def test_settings_defaults_match_confirmed_decisions() -> None:
    settings = Settings(_env_file=None)
    assert settings.quality_min_score == 0.80  # PRD 已确认的质检阈值
    # PM 已确认：用户只看到 1 张。gen_max_attempts 控制的是**内部**最多画几张：
    # 默认 2 —— 第 1 张被判不合格（fast 模式偶发 Logo 崩坏）时自动补 1 张再交付
    assert settings.gen_max_attempts == 2
    # 结构骨架（防自由创作）默认开启
    assert settings.enable_structure_reference is True
