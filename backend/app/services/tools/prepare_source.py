"""源图准备：文搜图 → 排序 → 视觉预筛 → 决定"该怎么画"。

## 为什么单独成一个模块（2026-09-21 线上事故复盘）

这段逻辑原先写在 `POST /api/v1/tasks` 的请求处理里，串行执行：
文搜图 → 下载候选图 → 视觉预筛。线上实测这些步骤合计约 **58 秒**
（其中下载候选图 ~27s、预筛 ~31s），而前端普通请求超时是 30 秒 ——
用户点「生成线稿」会在 30 秒时报超时，后端却还在跑。

现在它属于**后台流水线的一个阶段**（状态 `searching_source`）：
接口只做到「型号校对」就返回（约 2 秒），前端用轮询拿后续进度。
这样长耗时步骤不再受单次 HTTP 请求时限约束。
"""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.llm import ModelResolveOut
from app.schemas.task import SourceCandidate
from app.services.providers.base import CallRecorder
from app.services.tools.rank_source_images import rank_source_images
from app.services.tools.screen_source_images import screen_or_fallback
from app.services.tools.search_shoe_image import search_shoe_image

#: 可视作「型号直出」的判定说明（写入任务轨迹，便于复盘）
MODE_REASON = {
    "single": "预筛判定有可用参考图，只展示 1 张推荐图",
    "model_only": "预筛判定候选图都不适合当参考，默认直接用型号生成",
    "choose": "型号置信度不足，展开候选让用户自己判断",
}


def prepare_source_candidates(
    resolved: ModelResolveOut,
    *,
    settings: Settings,
    search_provider,
    judge,
    recorder: CallRecorder,
    trace=None,
) -> tuple[list[SourceCandidate], dict, str]:
    """返回 (候选图, 预筛摘要, 呈现模式)。

    能力边界：只在拿到**真实候选图**后才调用视觉预筛；
    搜图失败按错误类型抛出 AppError，由调用方决定状态（业务结果 vs 系统错误）。
    """
    candidates = search_shoe_image(
        resolved.normalized, search_provider, settings.search_max_images, recorder
    )
    ranked = rank_source_images(candidates)

    # 预筛：文搜图常返回"两只鞋合影 / 3/4 角度 / 背景杂乱"的资讯配图，
    # 直接用会把坏输入推给用户（实测已被风格闸门拦下）。一次视觉调用约 。
    ranked, screen_summary = screen_or_fallback(
        ranked,
        judge=judge,
        recorder=recorder,
        settings=settings,
        model_name=resolved.normalized,
        trace=trace,
    )

    # 系统先决定"该怎么画"，而不是把挑图丢给用户：
    # - 预筛判定有可用参考图 -> single：只展示 1 张推荐图（「就是这双，开始画」）
    # - 预筛判定都不适合     -> model_only：默认直接用型号生成
    #   （实测 0.829 vs 用坏图 0.605，Logo 0.90 vs 0.32 —— 坏参考图会把 Logo 带歪）
    # - 型号置信度不足       -> choose：展开多张让用户判断
    confident = resolved.confidence >= settings.source_confirm_confidence
    if not ranked or not confident:
        mode = "choose"
    elif screen_summary.get("usable", True):
        mode = "single"
    else:
        mode = "model_only"
    return ranked, screen_summary, mode
