"""质检判定（确定性代码）：画布硬指标、Logo 硬门槛、阈值边界。"""

from __future__ import annotations

import io

from PIL import Image

from app.core.config import STYLES_DIR, Settings
from app.schemas.llm import QualityReportOut
from app.services.cv.binarize import check_artwork, refine_lineart
from app.services.style.registry import StyleRegistry
from app.services.tools.verify_lineart import score_and_gate, style_blocking_issues


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


def test_logo_filled_hard_gate_blocks_hollow_logo() -> None:
    """标志性图形只画空心轮廓（logo_filled 低）→ 即使总分达标也判不合格。"""
    style = default_style()
    hollow = QualityReportOut(
        shoe_silhouette_match=1.0,
        logo_legibility=0.9,
        style_consistency=1.0,
        noise_level=1.0,
        logo_filled=0.2,
        laces_solid_ratio=0.0,
        text_legible=1.0,
    )
    score, passed, issues = score_and_gate(hollow, 1.0, style, 0.80)
    assert score >= 0.80
    assert passed is False
    assert any("logo_filled" in issue for issue in issues)


def test_laces_solid_ratio_upper_bound_blocks() -> None:
    """鞋带被涂成实心块（laces_solid_ratio 超上限）→ 不合格。"""
    style = default_style()
    solid_laces = QualityReportOut(
        shoe_silhouette_match=1.0,
        logo_legibility=0.9,
        style_consistency=1.0,
        noise_level=1.0,
        logo_filled=1.0,
        laces_solid_ratio=0.40,
        text_legible=1.0,
    )
    _score, passed, issues = score_and_gate(solid_laces, 1.0, style, 0.80)
    assert passed is False
    assert any("laces_solid_ratio" in issue for issue in issues)


def test_text_legible_is_soft_and_does_not_fail() -> None:
    """文字可辨度（text_legible）是软性：低分只触发兜底贴合，不决定成败。"""
    style = default_style()
    garbled_text = QualityReportOut(
        shoe_silhouette_match=1.0,
        logo_legibility=0.9,
        style_consistency=1.0,
        noise_level=1.0,
        logo_filled=1.0,
        laces_solid_ratio=0.0,
        text_legible=0.1,
    )
    _score, passed, _issues = score_and_gate(garbled_text, 1.0, style, 0.80)
    assert passed is True, "text_legible 不应成为成败门槛"


# ---------------- 风格区间的"硬/软"边界（线上真图冒烟修正，2026-09-23）----------------

#: 线上真图冒烟那一次的**实测**风格度量（docs/smoke-report-v2-upload.md）
#: 画稿本身是对的（质检 0.9325、Logo 实心、鞋带非实心、无排线）
REAL_CASE_METRICS = {
    "hatch_suspect": 0.0,
    "ink_ratio": 0.0545,
    "solid_black_share": 0.0537,
    "filled_block_share": 0.0149,  # ← 只有这一项低于观察区间下限，旧逻辑就靠它把任务判失败
}

REAL_CASE_REPORT = QualityReportOut(
    shoe_silhouette_match=0.92,
    logo_legibility=0.95,
    style_consistency=0.90,
    noise_level=0.93,
    logo_filled=1.0,
    laces_solid_ratio=0.0,
    text_legible=0.0,
)


def _targets() -> dict:
    style = default_style()
    return {
        key: (float(values[0]), float(values[1]))
        for key, values in (style.quality_gate.style_metrics or {}).items()
    }


def test_real_case_filled_block_below_band_does_not_block() -> None:
    """回归（真图实测）：只填 Logo 的正确画稿，实心块占比会低于旧下限 —— 不应判不合格。

    V2 填色规则就是"只填 Logo，中底/鞋面/鞋带一律不得涂实"，所以实心块本来就少；
    "Logo 到底填没填实" 已由语义闸门 logo_filled 负责，用像素占比当硬闸门会误杀。
    """
    style = default_style()
    blocking = style_blocking_issues(
        REAL_CASE_METRICS,
        _targets(),
        hard_keys=style.quality_gate.style_hard_keys,
        hard_max=style.quality_gate.style_hard_max,
    )
    assert blocking == [], f"这些偏离不应阻塞：{blocking}"

    score, passed, _issues = score_and_gate(
        REAL_CASE_REPORT, 1.0, style, 0.80, style_ok=False, style_blocked=False
    )
    assert score >= 0.90
    assert passed is True, "画稿正确、总分达标、硬闸门全过 → 必须判合格"


def test_hatch_strokes_still_block() -> None:
    """排线/素描笔触仍然是硬闸门（唯一能区分干净线稿与排线的指标）。"""
    style = default_style()
    blocked = style_blocking_issues(
        {**REAL_CASE_METRICS, "hatch_suspect": 34},
        _targets(),
        hard_keys=style.quality_gate.style_hard_keys,
        hard_max=style.quality_gate.style_hard_max,
    )
    assert any("hatch_suspect" in item for item in blocked)

    _score, passed, issues = score_and_gate(
        REAL_CASE_REPORT, 1.0, style, 0.80, style_ok=False, style_blocked=True, style_issues=blocked
    )
    assert passed is False
    assert any("风格一致性未达标" in item for item in issues)


def test_whole_area_blackened_still_blocks() -> None:
    """把中底/鞋面整块涂黑（大面积涂黑超上限）仍然不合格 —— 这是产品规则，不能放松。"""
    style = default_style()
    blocked = style_blocking_issues(
        {**REAL_CASE_METRICS, "filled_block_share": 0.14},
        _targets(),
        hard_keys=style.quality_gate.style_hard_keys,
        hard_max=style.quality_gate.style_hard_max,
    )
    assert any("filled_block_share" in item for item in blocked)


def test_settings_defaults_match_confirmed_decisions() -> None:
    settings = Settings(_env_file=None)
    assert settings.quality_min_score == 0.80  # PRD 已确认的质检阈值
    # PM 已确认：用户只看到 1 张。gen_max_attempts 控制的是**内部**最多画几张：
    # 默认 2 —— 第 1 张被判不合格（fast 模式偶发 Logo 崩坏）时自动补 1 张再交付
    assert settings.gen_max_attempts == 2
    # 结构骨架（防自由创作）默认开启
    assert settings.enable_structure_reference is True
