"""任务接口：创建 / 轮询 / 选源图 / 重新生成 / 取画稿 / 归档 / 取消。

约定（阶段文档 7.1）：
- 全部按当前身份（owner_id）过滤，跨 owner 一律 404；
- `model_not_found` / 搜图空结果这类**业务结果**用 201 + state 表达；
- 上游认证失败、限流、超时这类**系统错误**用 4xx/5xx + 统一错误结构。
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_identity, get_container
from app.core.errors import AppError, ErrorCode
from app.core.idgen import new_task_id, new_trace_id, now_iso
from app.core.paths import validate_manual_path
from app.schemas.archive import ArchiveCreateOut, ArchiveQuality, ArchiveSource
from app.schemas.enums import SOURCE_CREDIT, TaskState
from app.schemas.task import (
    ArchiveIn,
    ArtworkOut,
    RegenerateIn,
    ResolveInfo,
    SourceSelectIn,
    TaskActionOut,
    TaskCreateIn,
    TaskError,
    TaskOut,
    TaskRecord,
    UploadTaskCreateIn,
)
from app.services.cv.imageio import (
    crop_box,
    encode_png,
    open_image,
    open_image_upright,
    scale_box,
    shrink_pil_with_scale,
    validate_image_bytes,
)
from app.services.providers.base import CallRecorder
from app.services.emphasis import is_valid as emphasis_is_valid
from app.services.storage.task_store import TERMINAL_STATES
from app.services.tools.archive_shoe import archive_shoe
from app.services.tools.resolve_model import resolve_model
from app.services.tools.search_shoe_image import (
    fetch_candidate_preview,
    fetch_source_image,
)
from app.services.tools.select_artwork import pick_best_artwork
from app.services.workflow import hooks
from app.services.auth.quota import consume_generation
from app.services.workflow.journal import TraceWriter
from app.services.workflow.runner import EDGE_FILENAME, SOURCE_FILENAME
from app.services.workflow.state_machine import transit

router = APIRouter(prefix="/tasks", tags=["tasks"])

S = TaskState
SYSTEM_ERROR_CODES = {
    ErrorCode.UPSTREAM_AUTH_FAILED,
    ErrorCode.BUDGET_EXCEEDED,
    ErrorCode.SCHEMA_TOO_NEW,
    ErrorCode.STORAGE_WRITE_FAILED,
}


def _decode_upload_base64(data: str) -> bytes:
    raw = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    try:
        payload = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise AppError(ErrorCode.INVALID_INPUT, detail={"reason": "图片数据不是合法 base64"}) from exc
    if len(payload) < 64:
        raise AppError(ErrorCode.INVALID_INPUT, detail={"reason": "图片数据过短"})
    return payload


def _artwork_url(task_id: str, attempt: int) -> str:
    return f"/api/v1/tasks/{task_id}/artworks/{attempt}.png"


def _draft_url(task_id: str) -> str:
    return f"/api/v1/tasks/{task_id}/draft.png"


def to_task_out(record: TaskRecord) -> TaskOut:
    """响应控制在 ~2KB：候选画稿只给 URL，不给 base64。"""
    artworks = [
        ArtworkOut(
            attempt=item.attempt,
            url=_artwork_url(record.task_id, item.attempt),
            score=item.score,
            passed=item.passed,
            issues=item.issues,
        )
        for item in record.artworks
    ]
    #: 当前展示/待归档的那一张 = 最优稿（先看是否通过质检，再看分数）
    current = pick_best_artwork(record.artworks)
    return TaskOut(
        task_id=record.task_id,
        state=record.state,
        query=record.query,
        style_id=record.style_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        progress=record.progress,
        normalize=(
            record.resolve.model_dump()
            if (record.resolve.normalized or record.resolve.candidates)
            else None
        ),
        source_candidates=record.source.candidates,
        source_mode=record.source.mode,
        recommended_index=record.source.recommended_index,
        selected_index=record.source.selected_index,
        artworks=artworks,
        current_artwork_url=_artwork_url(record.task_id, current.attempt) if current else None,
        current_attempt=current.attempt if current else None,
        # 走过预处理（有画布）才有 CV 草稿；型号直出没有
        draft_url=_draft_url(record.task_id) if record.source.source_path else None,
        quality=record.quality.model_dump(),
        error=record.error.model_dump() if record.error else None,
        upstream_calls=record.upstream_calls,
        est_cost_cny=record.est_cost_cny,
        can={
            "select_source": record.state in {S.AWAITING_SOURCE_CONFIRM, S.RESOLVE_FAILED},
            "archive": record.state in {S.AWAITING_EFFECT_CONFIRM, S.FAILED} and bool(record.artworks),
            "regenerate": record.state in {S.AWAITING_EFFECT_CONFIRM, S.FAILED, S.INTERRUPTED},
            "cancel": record.state not in TERMINAL_STATES,
        },
    )


def _schedule(container, owner_id: str, task_id: str) -> None:
    if container.settings.pipeline_inline:
        # 仅测试用：在请求内同步跑完，保证断言可确定
        container.runner.run_sync(owner_id, task_id)
    else:
        container.runner.submit(owner_id, task_id)


@router.post("", status_code=201, response_model=TaskOut)
def create_task(
    payload: TaskCreateIn, request: Request, owner_id: str = Depends(current_identity)
) -> TaskOut:
    container = get_container(request)
    settings = container.settings
    style = container.styles.resolve_for_new_task(payload.style_id, settings.style_id)

    # 额度：1 次生成 = 扣 1 次（本地开发未启用登录时不计数）
    consume_generation(settings, container.invite_store, owner_id)

    record = TaskRecord(
        task_id=new_task_id(),
        owner_id=owner_id,
        state=S.CREATED,
        created_at=now_iso(),
        updated_at=now_iso(),
        style_id=style.style_id,
        query=payload.query,
        trace_id=new_trace_id(),
    )
    container.task_store.create(record)
    trace = TraceWriter(container.backend, owner_id, record.task_id)
    recorder = CallRecorder(settings.task_max_upstream_calls, settings)

    transit(record, S.RESOLVING, event="resolve_start", detail={"query": payload.query})
    record.progress = {"step": "resolving", "label": "正在确认型号", "percent": 5}
    container.task_store.save(record)
    try:
        resolved = resolve_model(payload.query, container.providers.resolver, recorder)
    except AppError as exc:
        record.error = TaskError(code=exc.code.value, message=exc.message, detail=exc.detail)
        record.state = S.FAILED
        record.progress = {"step": "failed", "label": "型号校对失败", "percent": 100}
        container.task_store.save(record)
        trace.write("resolve_failed", code=exc.code.value)
        raise

    record.resolve = ResolveInfo(**resolved.model_dump())
    record.upstream_calls = recorder.total_calls
    record.est_cost_cny = recorder.total_cost
    trace.write(
        "resolve_result",
        query=payload.query,
        normalized=resolved.normalized,
        exists=resolved.exists,
        confidence=resolved.confidence,
        brand=resolved.brand,
    )

    if not resolved.exists:
        transit(
            record,
            S.MODEL_NOT_FOUND,
            event="model_not_found",
            detail={"candidates": [c.name for c in resolved.candidates]},
        )
        record.progress = {"step": "model_not_found", "label": "没找到这个型号", "percent": 100}
        container.task_store.save(record)
        return to_task_out(record)

    # 接口到此为止返回（约 2 秒）：型号校对结果是用户最先要看的东西，同步给到。
    # 后续「文搜图 + 下载候选图 + 视觉预筛」线上实测约 58 秒，放进后台流水线
    # （状态 searching_source），否则请求会被前端 30s 超时或网关限制卡断。
    record.upstream_calls = recorder.total_calls
    record.est_cost_cny = recorder.total_cost
    transit(record, S.SEARCHING_SOURCE, event="source_search_start")
    record.progress = {"step": "searching_source", "label": "正在找这双鞋的参考图", "percent": 10}
    container.task_store.save(record)

    _schedule(container, owner_id, record.task_id)

    # 测试/内联模式下流水线已同步跑完，回读一次拿到最新状态（生产返回 searching_source）
    return to_task_out(container.task_store.get(owner_id, record.task_id))


@router.post("/upload", status_code=201, response_model=TaskOut)
def create_upload_task(
    payload: UploadTaskCreateIn, request: Request, owner_id: str = Depends(current_identity)
) -> TaskOut:
    """上传图生成（V2 输入方式）：图 + 裁切框 + 已体检结论。

    与 ``POST /tasks`` 的分工：型号输入走「校对 → 搜图 → 确认源图」；
    上传图在 ``POST /inspect`` 已经做完「裁切 → 体检 → 三档判定」，这里不再调用视觉模型，
    只把用户确认过的裁切图存成源图，直接进入预处理（去背景 + 3:2 归一化）。
    """
    container = get_container(request)
    settings = container.settings
    style = container.styles.resolve_for_new_task(payload.style_id, settings.style_id)

    # 额度：1 次生成 = 扣 1 次（体检另计，不在此列）
    consume_generation(settings, container.invite_store, owner_id)

    # 与 /inspect 同一套坐标系约定：EXIF 摆正 → 缩图 → 裁切框乘同一个系数
    image, ratio = shrink_pil_with_scale(
        open_image_upright(_decode_upload_base64(payload.image_base64)), settings.max_upload_edge
    )
    box = payload.crop.as_tuple()
    if ratio != 1.0:
        box = scale_box(box, ratio)
    cropped = crop_box(image, box)
    png = encode_png(cropped.convert("RGB"))

    name = payload.inspect.name_for_archive or payload.inspect.display_name or "上传的球鞋"
    record = TaskRecord(
        task_id=new_task_id(),
        owner_id=owner_id,
        state=S.PREPROCESSING,
        created_at=now_iso(),
        updated_at=now_iso(),
        style_id=style.style_id,
        query=name,
        inspect=payload.inspect,
        trace_id=new_trace_id(),
    )
    container.task_store.create(record)
    container.asset_store.put_task_file(owner_id, record.task_id, SOURCE_FILENAME, png)
    record.source.source_path = None
    record.progress = {"step": "preprocessing", "label": "正在把照片整理成 3:2 画布", "percent": 15}
    container.task_store.save(record)

    TraceWriter(container.backend, owner_id, record.task_id).write(
        "upload_received",
        display_name=payload.inspect.display_name,
        logo_type=payload.inspect.logo_type,
        logo_position=payload.inspect.logo_position,
        texts=payload.inspect.texts,
        crop=payload.crop.as_tuple(),
    )

    _schedule(container, owner_id, record.task_id)
    return to_task_out(container.task_store.get(owner_id, record.task_id))


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, request: Request, owner_id: str = Depends(current_identity)) -> TaskOut:
    record = get_container(request).task_store.get(owner_id, task_id)
    return to_task_out(record)


@router.post("/{task_id}/source", status_code=202, response_model=TaskActionOut)
def select_source(
    task_id: str,
    payload: SourceSelectIn,
    request: Request,
    owner_id: str = Depends(current_identity),
) -> TaskActionOut:
    container = get_container(request)
    settings = container.settings
    record = container.task_store.get(owner_id, task_id)
    if record.state not in {S.AWAITING_SOURCE_CONFIRM, S.RESOLVE_FAILED}:
        raise AppError(ErrorCode.INVALID_STATE, detail={"state": record.state.value})

    model_only = bool(payload.use_model_only)
    if model_only:
        # 兜底：候选图都不适合当参考（或压根搜不到图）-> 直接用型号生成。
        # 注意：这条路径**不需要候选图**，因此搜图为空时用户同样有出路。
        best = record.source.candidates[0] if record.source.candidates else None
        # 注意：不把这张不可用的图存成质检基准（否则"鞋型不符"是坏图造成的误判）
        if best is not None:
            record.source.selected_index = best.index
            record.source.selected_provider = best.provider
            record.source.selected_url = best.url
        record.source.manual = False
        record.source.use_model_only = True
        record.source.source_path = None
        record.error = None
        transit(record, S.PREPROCESSING, event="model_only_selected", detail={"model": record.resolve.normalized})
        record.progress = {"step": "generating", "label": "正在线条描摹（约 30–60 秒）", "percent": 40}
        container.task_store.save(record)
        hooks.run("after_source_selected", {"owner_id": owner_id, "task_id": task_id})
        TraceWriter(container.backend, owner_id, task_id).write(
            "source_selected", manual=False, model_only=True, model_name=record.resolve.normalized
        )
        _schedule(container, owner_id, task_id)
        record = container.task_store.get(owner_id, task_id)
        return TaskActionOut(task_id=task_id, state=record.state, message="已按型号开始生成")

    manual = bool(payload.manual_url or payload.manual_path)
    effective_index: int | None = None
    if manual:
        if not (settings.enable_manual_source and settings.env == "dev"):
            raise AppError(ErrorCode.MANUAL_SOURCE_DISABLED)
        if payload.manual_path:
            path = validate_manual_path(payload.manual_path, settings.allowed_source_dir_list)
            raw = path.read_bytes()
            validate_image_bytes(raw)
            provider, url = "manual_file", None
        else:
            from app.schemas.task import SourceCandidate

            candidate = SourceCandidate(index=0, provider="manual_url", url=payload.manual_url)
            raw = fetch_source_image(candidate)
            provider, url = "manual_url", payload.manual_url
    else:
        # 未指定 = 采用系统推荐的那张（界面上的「就是这双，开始画」）
        effective_index = (
            payload.selected_index
            if payload.selected_index is not None
            else record.source.recommended_index
        )
        if effective_index >= len(record.source.candidates):
            raise AppError(ErrorCode.SOURCE_NOT_FOUND, detail={"index": effective_index})
        candidate = record.source.candidates[effective_index]
        raw = fetch_source_image(candidate)
        provider, url = candidate.provider, candidate.url

    png = encode_png(open_image(raw))
    container.asset_store.put_task_file(owner_id, task_id, SOURCE_FILENAME, png)

    record.source.selected_index = effective_index
    record.source.selected_provider = provider
    record.source.selected_url = url
    record.source.manual = manual
    record.source.source_path = None
    record.error = None
    transit(record, S.PREPROCESSING, event="source_selected", detail={"provider": provider})
    record.progress = {"step": "preprocessing", "label": "正在把照片整理成 3:2 画布", "percent": 15}
    container.task_store.save(record)

    hooks.run("after_source_selected", {"owner_id": owner_id, "task_id": task_id})
    TraceWriter(container.backend, owner_id, task_id).write(
        "source_selected",
        index=payload.selected_index,
        manual=manual,
        provider=provider,
        url=url,
    )
    _schedule(container, owner_id, task_id)
    record = container.task_store.get(owner_id, task_id)
    return TaskActionOut(task_id=task_id, state=record.state, message="已开始生成，可以离开本页稍后回来")


@router.post("/{task_id}/regenerate", status_code=202, response_model=TaskActionOut)
def regenerate(
    task_id: str,
    payload: RegenerateIn,
    request: Request,
    owner_id: str = Depends(current_identity),
) -> TaskActionOut:
    container = get_container(request)
    record = container.task_store.get(owner_id, task_id)
    if record.state not in {S.AWAITING_EFFECT_CONFIRM, S.FAILED, S.INTERRUPTED}:
        raise AppError(ErrorCode.INVALID_STATE, detail={"state": record.state.value})
    # 型号直出（model_only）本来就没有标准画布 —— 不能因此拒绝"重新生成"
    if not record.source.source_path and not record.source.use_model_only:
        raise AppError(ErrorCode.INVALID_STATE, detail={"reason": "缺少源图，请重新输入"})

    # 手动"重新生成"同样消耗 1 次额度（质检自动重试不计数）
    consume_generation(
        container.settings, container.invite_store, owner_id
    )

    # 用户选的修正方向：只接受已知的键（**不能把任意字符串拼进提示词**）。
    # 认不出来就当没选，不让一个拼错的 key 把这次重画变成一次无意义的烧钱。
    emphasis = payload.emphasis.strip() if payload.emphasis else ""
    if emphasis and not emphasis_is_valid(emphasis):
        emphasis = ""
    record.regenerate_emphasis = emphasis

    transit(
        record,
        S.GENERATING,
        event="user_regenerate",
        detail={"note": payload.note or "", "emphasis": emphasis},
    )
    record.progress = {"step": "generating", "label": "重新生成中", "percent": 45}
    container.task_store.save(record)
    # 轨迹原料：记录用户为什么要求重生成（PRD 4.7）
    TraceWriter(container.backend, owner_id, task_id).write(
        "user_regenerate",
        note=payload.note or "",
        emphasis=emphasis,
        round=record.attempts.round + 1,
    )
    _schedule(container, owner_id, task_id)
    record = container.task_store.get(owner_id, task_id)
    return TaskActionOut(task_id=task_id, state=record.state, message="正在重新生成")


@router.get("/{task_id}/candidates/{index}.png")
def get_candidate_preview(
    task_id: str, index: int, request: Request, owner_id: str = Depends(current_identity)
) -> Response:
    """候选图预览（后端代理 + 降采样 + 缓存）。

    不让前端直接加载候选图 URL：防盗链/CORS 不可控，且会把使用者 IP 暴露给第三方图站。
    """
    container = get_container(request)
    record = container.task_store.get(owner_id, task_id)
    if index < 0 or index >= len(record.source.candidates):
        # 文件类接口用 404（不是 422 参数错误）：资源不存在
        raise AppError(ErrorCode.SOURCE_NOT_FOUND, status_code=404, detail={"index": index})

    cache_key = container.asset_store.task_key(owner_id, task_id, f"candidate_{index}.png")
    if container.asset_store.exists(cache_key):
        data = container.asset_store.get(cache_key)
    else:
        data = fetch_candidate_preview(record.source.candidates[index])
        container.asset_store.put(cache_key, data)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{task_id}/draft.png")
def get_draft(
    task_id: str, request: Request, owner_id: str = Depends(current_identity)
) -> Response:
    """CV 草稿（边缘骨架图）：生成 AI 稿期间给前端做「扫过式揭示」动效用。

    它是预处理阶段纯 CV 抽出来的（约 1 秒、本机计算），不是最终交付物；
    型号直出（无画布）的任务没有它，前端据此退回纯进度卡片。
    """
    container = get_container(request)
    record = container.task_store.get(owner_id, task_id)
    if record.source.use_model_only or not record.source.source_path:
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND, detail={"reason": "该任务没有 CV 草稿"})
    key = container.asset_store.task_key(owner_id, task_id, EDGE_FILENAME)
    if not container.asset_store.exists(key):
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND, detail={"reason": "草稿尚未生成"})
    return Response(
        content=container.asset_store.get(key),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{task_id}/artworks/{attempt}.png")
def get_artwork(
    task_id: str, attempt: int, request: Request, owner_id: str = Depends(current_identity)
) -> Response:
    container = get_container(request)
    record = container.task_store.get(owner_id, task_id)
    item = next((a for a in record.artworks if a.attempt == attempt), None)
    if item is None:
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND, detail={"attempt": attempt})
    try:
        data = container.asset_store.get(item.path)
    except Exception as exc:
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND) from exc
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/{task_id}/archive", status_code=201, response_model=ArchiveCreateOut)
def archive_task(
    task_id: str,
    payload: ArchiveIn,
    request: Request,
    owner_id: str = Depends(current_identity),
) -> ArchiveCreateOut:
    container = get_container(request)
    settings = container.settings
    record = container.task_store.get(owner_id, task_id)
    if record.state not in {S.AWAITING_EFFECT_CONFIRM, S.FAILED}:
        raise AppError(ErrorCode.INVALID_STATE, detail={"state": record.state.value})
    if not record.artworks:
        raise AppError(ErrorCode.ARTWORK_NOT_FOUND)

    if payload.attempt is not None:
        item = next((a for a in record.artworks if a.attempt == payload.attempt), None)
        if item is None:
            raise AppError(ErrorCode.ARTWORK_NOT_FOUND, detail={"attempt": payload.attempt})
    else:
        # 不指定就用最优稿：**先看有没有通过质检，再看分数**。
        # 不能只比分数 —— 同分时 max 会留下先出现的那张（实测 AF1 因此归档了"勾没填"、
        # 且质检明确判过未通过的第 1 张）。见 services/tools/select_artwork.py。
        item = pick_best_artwork(record.artworks)

    artwork_png = container.asset_store.get(item.path)
    # 上传图（V2）用体检识别的「品牌 + 型号」当默认标题；型号输入路径仍用校对结果
    upload_name = record.inspect.name_for_archive if record.inspect else ""
    model_name = (payload.model_name or upload_name or record.resolve.normalized or record.query).strip()

    transit(record, S.ARCHIVING, event="archive_start", detail={"attempt": item.attempt})
    record.progress = {"step": "archiving", "label": "归档中", "percent": 95}
    container.task_store.save(record)

    style = container.styles.get(record.style_id)
    entry = archive_shoe(
        archive_store=container.archive_store,
        asset_store=container.asset_store,
        settings=settings,
        owner_id=owner_id,
        model_name=model_name,
        model_name_input=record.query,
        artwork_png=artwork_png,
        style=style,
        source=ArchiveSource(
            provider=record.source.selected_provider or container.providers.search.name,
            url=record.source.selected_url,
            credit=SOURCE_CREDIT,
            selected_by="user",
        ),
        quality=ArchiveQuality(
            score=item.score, attempts=record.attempts.used_in_round, checks=record.quality.checks
        ),
        trace_id=record.trace_id,
        date_text=payload.date_text,
        story=payload.story,
    )

    transit(record, S.ARCHIVED, event="archived", detail={"shoe_id": entry.shoe_id})
    record.progress = {"step": "archived", "label": "已归档", "percent": 100}
    container.task_store.save(record)
    hooks.run("after_archive", {"owner_id": owner_id, "task_id": task_id, "shoe_id": entry.shoe_id})
    TraceWriter(container.backend, owner_id, task_id).write(
        "archived",
        shoe_id=entry.shoe_id,
        attempt=item.attempt,
        score=item.score,
        date_text=entry.date_text,
        date_sort_key=entry.date_sort_key,
        story=entry.story or "",
        upstream_calls=record.upstream_calls,
        est_cost_cny=record.est_cost_cny,
    )
    return ArchiveCreateOut(
        shoe_id=entry.shoe_id,
        artwork_url=f"/api/v1/archive/{entry.shoe_id}/artwork.png",
        date_sort_key=entry.date_sort_key,
        created_at=entry.created_at,
    )


@router.post("/{task_id}/cancel", response_model=TaskActionOut)
def cancel_task(
    task_id: str, request: Request, owner_id: str = Depends(current_identity)
) -> TaskActionOut:
    container = get_container(request)
    record = container.task_store.get(owner_id, task_id)
    if record.state in TERMINAL_STATES:
        return TaskActionOut(task_id=task_id, state=record.state, message="任务已结束")
    transit(record, S.CANCELLED, event="cancelled_by_user")
    record.progress = {"step": "cancelled", "label": "已放弃", "percent": 100}
    container.task_store.save(record)
    return TaskActionOut(task_id=task_id, state=record.state, message="已放弃本次生成")
