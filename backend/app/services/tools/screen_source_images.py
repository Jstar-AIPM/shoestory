"""工具：候选源图可用性预筛（s17 目标闭环的一环）。

为什么必须做：文搜图返回的常是"资讯配图/开箱照"——两只鞋合影、3/4 角度、背景杂乱。
若直接拿来当参考图，线稿会偏离 PRD 的"单只、正侧面、白底"规范（实测会被风格闸门拦下）。
因此在推荐给用户之前，先用**一次**视觉调用对候选图打分（成本约 ）。

失败不阻塞：预筛出错时退回启发式排序（并在任务里记录原因）。
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.llm import SourceScreenOut
from app.schemas.task import SourceCandidate
from app.services.providers.base import CallRecorder, QualityJudge
from app.services.tools.search_shoe_image import fetch_candidate_preview


def screen_source_images(
    candidates: list[SourceCandidate],
    *,
    judge: QualityJudge,
    recorder: CallRecorder,
    settings: Settings,
    model_name: str,
) -> tuple[list[SourceCandidate], dict]:
    """对前 N 张候选图做可用性预筛，返回 (重排后的候选, 汇总信息)。"""
    limit = max(1, settings.source_screen_max_candidates)
    targets = candidates[:limit]
    images: list[bytes] = []
    for candidate in targets:
        images.append(
            fetch_candidate_preview(candidate, max_width=settings.ark_max_image_edge)
        )

    report: SourceScreenOut = judge.screen_sources(
        images=images, model_name=model_name, recorder=recorder
    )
    by_index = {item.index: item for item in report.results}

    # 判定"可用"用**布尔条件**，不用 0-1 分数：
    # 实测模型给的分数有波动（同一张"两只鞋合影"时而 0.25、时而过 0.6），但四个布尔判断很稳定。
    # 因此：单只鞋 AND 正侧面 AND 背景干净 AND 清晰 —— 四项全真才算可用；分数只用于排序。
    def is_usable(item) -> bool:
        return bool(item.single_shoe and item.side_view and item.clean_background and item.sharp)

    scored: list[tuple[int, float, SourceCandidate]] = []
    for position, candidate in enumerate(candidates):
        if position < limit and position in by_index:
            item = by_index[position]
            scored.append(
                (
                    1 if is_usable(item) else 0,
                    item.score,
                    candidate.model_copy(
                        update={
                            "screen_score": item.score,
                            "screen_reason": item.reason,
                            "screen_flags": item.flags(),
                            "screen_usable": is_usable(item),
                        }
                    ),
                )
            )
        else:
            # 超出预筛范围的候选：既不推荐也不否决，排在最后
            scored.append((-1, -1.0, candidate))

    ordered = sorted(scored, key=lambda row: (row[0], row[1]), reverse=True)
    renumbered: list[SourceCandidate] = []
    for position, (_usable_flag, _score, candidate) in enumerate(ordered):
        renumbered.append(candidate.model_copy(update={"index": position, "rank": position}))

    usable_candidates = [row for row in scored if row[0] == 1]
    best_index = renumbered[0].index if usable_candidates or renumbered else -1
    summary = {
        "screened": len(targets),
        # 只有候选图真的"单只+正侧面+干净+清晰"时才算可用；否则引导走"型号直出"
        "usable": bool(usable_candidates),
        "usable_count": len(usable_candidates),
        "best_index": best_index,
        "best_score": round(usable_candidates[0][1], 3) if usable_candidates else 0.0,
        "criteria": "single_shoe & side_view & clean_background & sharp（四项全真才算可用）",
        "results": [item.model_dump() for item in report.results],
    }
    return renumbered, summary


def screen_or_fallback(
    candidates: list[SourceCandidate],
    *,
    judge: QualityJudge,
    recorder: CallRecorder,
    settings: Settings,
    model_name: str,
    trace=None,
) -> tuple[list[SourceCandidate], dict]:
    if not settings.enable_source_screening:
        return candidates, {"screened": 0, "skipped": True}
    try:
        return screen_source_images(
            candidates,
            judge=judge,
            recorder=recorder,
            settings=settings,
            model_name=model_name,
        )
    except AppError as exc:
        # 预筛失败不阻塞主链路：退回启发式排序，并如实记录
        if trace is not None:
            trace.write("source_screen_failed", code=exc.code.value)
        return candidates, {"screened": 0, "failed": exc.code.value}
