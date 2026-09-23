"""工具（s17 目标闭环）：画稿独立质检 verify_lineart。

判定归代码：
- 画布比例/纯二值/白底由 `check_artwork` 确定性判定（canvas_ratio 分项）；
- 四项内容质量由独立视觉模型给分；
- 通过条件 = 加权总分 >= min_score 且命中所有 hard_gate（Logo 硬门槛 + 画布必须满分）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.schemas.llm import QualityReportOut
from app.services.cv.binarize import check_artwork
from app.services.cv.style import compare_to_targets, measure_style
from app.services.providers.base import CallRecorder, QualityJudge
from app.services.style.loader import StyleTemplate


@dataclass
class VerifyResult:
    report: QualityReportOut
    artwork_check: dict
    score: float
    passed: bool
    issues: list[str] = field(default_factory=list)
    style_metrics: dict = field(default_factory=dict)
    style_ok: bool = True
    #: 风格偏离中**真正算不合格**的那部分（style_ok 可能因为"观察区间"偏离而为 False，
    #: 但那不代表不合格 —— 二者必须分开，否则会把合格产出误杀）
    style_blocked: bool = False


def style_blocking_issues(
    metrics: dict,
    targets: dict,
    *,
    hard_keys: list[str] | None = None,
    hard_max: dict[str, float] | None = None,
) -> list[str]:
    """从风格度量里挑出**真正当闸门**的偏离。

    区分来源（2026-09-23 线上真图冒烟）：风格模板里写的是
    “hatch_suspect 是硬判据，其余是指标观察区间”，但代码把**任何**区间偏离都当不合格 ——
    于是一张质检 0.93、Logo 实心、鞋带正确的好画稿，因为
    `filled_block_share=0.0149 < 0.020`（V2 规则只许 Logo 填色，实心块本来就少）
    被判不合格，白烧两次生成（本机计算）并给用户看失败页。
    """
    out: list[str] = []
    for key in hard_keys or []:
        if key not in targets:
            continue
        low, high = targets[key]
        value = metrics.get(key)
        if value is not None and not (low <= value <= high):
            out.append(f"{key}={value} 超出硬闸门区间 [{low}, {high}]")
    for key, ceiling in (hard_max or {}).items():
        value = metrics.get(key)
        if value is not None and value > ceiling:
            out.append(f"{key}={value} 超出硬上限 {ceiling}（禁止整块涂黑）")
    return out


def score_and_gate(
    report: QualityReportOut,
    canvas_score: float,
    style: StyleTemplate,
    min_score: float,
    *,
    style_ok: bool = True,
    style_issues: list[str] | None = None,
    style_blocked: bool | None = None,
) -> tuple[float, bool, list[str]]:
    weights = dict(style.quality_gate.weights)
    scores: dict[str, float] = {
        "shoe_silhouette_match": report.shoe_silhouette_match,
        "logo_legibility": report.logo_legibility,
        "style_consistency": report.style_consistency,
        "noise_level": report.noise_level,
        "canvas_ratio": canvas_score,
        # 以下三项不参与加权（weights 里没有），只供硬闸门用
        "logo_filled": report.logo_filled,
        "laces_solid_ratio": report.laces_solid_ratio,
        "text_legible": report.text_legible,
    }
    total_weight = sum(weights.get(key, 0.0) for key in scores) or 1.0
    score = sum(scores[key] * weights.get(key, 0.0) for key in scores) / total_weight
    score = round(score, 4)

    issues = list(report.issues)
    passed = score >= min_score
    # 硬下限：标志性 Logo 必须填实、Logo 可辨识、画布满分……
    for key, threshold in (style.quality_gate.hard_gate or {}).items():
        value = scores.get(key, 0.0)
        if value < threshold:
            passed = False
            issues.append(f"{key} 未达硬门槛（{value:.2f} < {threshold:.2f}）")
    # 硬上限：鞋带不得被涂成实心块等
    for key, ceiling in (style.quality_gate.hard_max or {}).items():
        value = scores.get(key, 0.0)
        if value > ceiling:
            passed = False
            issues.append(f"{key} 超出硬上限（{value:.2f} > {ceiling:.2f}）")
    if not passed and score < min_score:
        issues.append(f"加权总分 {score:.2f} 低于阈值 {min_score:.2f}")
    if style_blocked is None:
        style_blocked = not style_ok
    if style_blocked:
        # 风格一致性由确定性代码判定（参考图量化得出），不信模型
        passed = False
        issues.extend(f"风格一致性未达标：{item}" for item in (style_issues or []))
    return score, passed, issues


def verify_lineart(
    *,
    model_name: str,
    style: StyleTemplate,
    source_png: bytes | None,
    artwork_png: bytes,
    judge: QualityJudge,
    recorder: CallRecorder,
    settings: Settings,
) -> VerifyResult:
    artwork_check = check_artwork(artwork_png, settings.artwork_width, settings.artwork_height)
    style_metrics = measure_style(artwork_png)
    targets = {
        key: (float(values[0]), float(values[1]))
        for key, values in (style.quality_gate.style_metrics or {}).items()
        if isinstance(values, (list, tuple)) and len(values) == 2
    }
    style_ok, style_issues = compare_to_targets(style_metrics, targets)
    blocking = style_blocking_issues(
        style_metrics,
        targets,
        hard_keys=style.quality_gate.style_hard_keys,
        hard_max=style.quality_gate.style_hard_max,
    )
    artwork_check = {**artwork_check, "style_metrics": style_metrics, "style_ok": style_ok}
    report = judge.judge(
        model_name=model_name,
        style=style,
        source_png=source_png,
        artwork_png=artwork_png,
        recorder=recorder,
    )
    score, passed, issues = score_and_gate(
        report,
        artwork_check["canvas_score"],
        style,
        settings.quality_min_score,
        style_ok=style_ok,
        style_issues=blocking or style_issues,
        style_blocked=bool(blocking),
    )
    return VerifyResult(
        report=report,
        artwork_check=artwork_check,
        score=score,
        passed=passed,
        issues=issues,
        style_metrics=style_metrics,
        style_ok=style_ok,
        style_blocked=bool(blocking),
    )
