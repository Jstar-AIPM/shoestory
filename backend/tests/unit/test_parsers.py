"""解析器（纯函数）：宽容解析 + 强校验，绝不猜测模型意图。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.schemas.llm import ModelResolveOut, QualityReportOut
from app.services.parsers import parse_json_loose, validate_llm_output

GOOD_RESOLVE = (
    '{"normalized": "Nike KD 12", "brand": "Nike", "confidence": 0.93, "exists": true,'
    ' "candidates": [], "note": "补全品牌"}'
)
GOOD_QUALITY = (
    '{"shoe_silhouette_match": 0.9, "logo_legibility": 0.8, "style_consistency": 0.9,'
    ' "noise_level": 0.85, "issues": [], "verdict": "pass", "reason": "OK"}'
)


@pytest.mark.parametrize(
    "text",
    [
        GOOD_RESOLVE,
        f"```json\n{GOOD_RESOLVE}\n```",
        f"好的，结果如下：\n{GOOD_RESOLVE}\n希望有帮助。",
        f"{GOOD_RESOLVE}\n{{'extra': '混在后面的对象'}}",
    ],
)
def test_loose_parse_tolerates_common_formats(text: str) -> None:
    parsed = parse_json_loose(text)
    assert parsed["normalized"] == "Nike KD 12"


@pytest.mark.parametrize("text", ["", "没有任何 JSON", "{bad json", "[1,2,3]"])
def test_loose_parse_rejects_garbage(text: str) -> None:
    with pytest.raises(AppError) as excinfo:
        parse_json_loose(text)
    assert excinfo.value.code is ErrorCode.LLM_OUTPUT_INVALID


def test_validate_model_resolve_ok() -> None:
    result = validate_llm_output(ModelResolveOut, GOOD_RESOLVE)
    assert result.normalized == "Nike KD 12"
    assert result.exists is True


def test_missing_field_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_llm_output(ModelResolveOut, '{"brand": "Nike", "confidence": 0.9, "exists": true}')
    assert excinfo.value.code is ErrorCode.LLM_OUTPUT_INVALID


def test_confidence_as_string_rejected() -> None:
    text = '{"normalized": "Nike KD 12", "brand": "Nike", "confidence": "很高", "exists": true}'
    with pytest.raises(AppError):
        validate_llm_output(ModelResolveOut, text)


def test_not_exists_requires_candidates_and_empty_normalized() -> None:
    with pytest.raises(AppError):
        validate_llm_output(
            ModelResolveOut,
            '{"normalized": "Nike KD 99", "brand": "Nike", "confidence": 0.9, "exists": false}',
        )
    result = validate_llm_output(
        ModelResolveOut,
        '{"normalized": "乱编", "brand": "", "confidence": 0.2, "exists": false,'
        ' "candidates": [{"name": "Nike KD 12", "reason": "相近"}]}',
    )
    assert result.normalized == ""  # 禁止编造型号
    assert result.candidates[0].name == "Nike KD 12"


def test_low_confidence_forces_not_exists() -> None:
    result = validate_llm_output(
        ModelResolveOut,
        '{"normalized": "x", "brand": "", "confidence": 0.4, "exists": true,'
        ' "candidates": [{"name": "Nike KD 12"}]}',
    )
    assert result.exists is False
    assert result.normalized == ""


def test_quality_scores_range_and_types() -> None:
    assert validate_llm_output(QualityReportOut, GOOD_QUALITY).logo_legibility == 0.8
    for bad in (
        GOOD_QUALITY.replace("0.8", "1.5"),
        GOOD_QUALITY.replace("0.9,", "-0.1,", 1),
        GOOD_QUALITY.replace('"issues": []', '"issues": "没有"'),
        GOOD_QUALITY.replace('"issues": []', '"issues": [1, 2]'),
    ):
        with pytest.raises(AppError) as excinfo:
            validate_llm_output(QualityReportOut, bad)
        assert excinfo.value.code is ErrorCode.LLM_OUTPUT_INVALID
