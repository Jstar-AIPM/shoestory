"""工具：候选图排序（rank_source_images）。

阶段 1 用**确定性启发式**排序（不额外花视觉调用费）：
1. 官方文搜图返回的 `BlurDes`（清晰/一般清晰/模糊）——免费的清晰度信号
2. `Watermark`（0=无水印）——水印会干扰线稿
3. 尺寸与横构图（正侧面多为横构图）
4. 官方 RankScore

模型排序（ENABLE_VISION_RANK）留作可选能力，默认关闭。
"""

from __future__ import annotations

from app.schemas.task import SourceCandidate

_BLUR_SCORE = {"清晰": 2.0, "一般清晰": 1.0, "模糊": -2.0}


def _score(candidate: SourceCandidate) -> tuple[float, float, float, float]:
    blur = _BLUR_SCORE.get(getattr(candidate, "blur", None) or "", 0.0)
    watermark = 1.0 if str(getattr(candidate, "watermark", "")) in {"0", "False", "false"} else 0.0
    width = candidate.width or 0
    height = candidate.height or 0
    ratio = (width / height) if height else 0.0
    landscape = 1.0 if 1.15 <= ratio <= 2.0 else 0.0
    big_enough = 1.0 if width >= 800 else 0.0
    rank_score = float(getattr(candidate, "rank_score", 0) or 0.0)
    return (blur + watermark, landscape + big_enough, rank_score, float(width * height))


def rank_source_images(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    """返回重新编号（index=0..n-1）后的候选列表；index 即界面选择用的序号。"""
    ordered = sorted(candidates, key=_score, reverse=True)
    ranked: list[SourceCandidate] = []
    for position, item in enumerate(ordered):
        ranked.append(item.model_copy(update={"index": position, "rank": position}))
    return ranked
