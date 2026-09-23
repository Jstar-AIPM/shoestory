"""流水线执行器（s11 后台任务 + s16 工作流运行时）。

形态固定，由代码状态机驱动：
  预处理(去背景 -> 3:2 白底画布) -> [生成 -> 后处理 -> 质检] 循环（上限 3 次/轮）
  -> 达标则 awaiting_effect_confirm（人工确认点，持久化）

- 每步都落盘（任务文件 + trace JSONL），进程重启后可恢复；
- 上游调用统一走 CallRecorder（成本护栏，硬上限 10 次/任务）；
- 不做开放式 Agent Loop（内部工程笔记 4.4）。
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.schemas.enums import STAGING_ARTWORK_TEMPLATE, TaskState
from app.schemas.llm import ModelResolveOut
from app.schemas.task import ArtworkCandidate, QualityInfo, SourceInfo, TaskError, TaskRecord
from app.services.providers.base import CallRecorder, ProviderBundle
from app.services.storage.asset_store import AssetStore
from app.services.storage.backend import StorageBackend
from app.services.storage.task_store import TERMINAL_STATES, TaskStore
from app.services.style.loader import StyleTemplate
from app.services.style.registry import StyleRegistry
from app.services.cv.edges import extract_edge_map
from app.services.cv.text_stamp import TextStamp, build_text_stamp, composite_text_stamps
from app.services.tools.generate_lineart import generate_lineart
from app.services.tools.normalize_view import normalize_view
from app.services.tools.prepare_source import MODE_REASON, prepare_source_candidates
from app.services.tools.refine_lineart import refine_lineart
from app.services.tools.segment_shoe import segment_shoe
from app.services.tools.verify_lineart import verify_lineart
from app.services.workflow import hooks
from app.services.workflow.journal import TraceWriter
from app.services.workflow.state_machine import transit

logger = logging.getLogger(__name__)

SOURCE_FILENAME = "source_0.png"
CUTOUT_FILENAME = "cutout.png"
CANVAS_FILENAME = "canvas_3x2.png"
EDGE_FILENAME = "edge_map.png"

S = TaskState

PROGRESS: dict[TaskState, tuple[str, str, int]] = {
    S.SEARCHING_SOURCE: ("searching_source", "正在找这双鞋的参考图", 10),
    S.PREPROCESSING: ("preprocessing", "正在把照片整理成 3:2 画布", 15),
    S.GENERATING: ("generating", "正在线条描摹（约 30–60 秒）", 45),
    S.REFINING: ("refining", "正在把线条整理干净", 72),
    S.VERIFYING: ("verifying", "正在自检（对照风格与 Logo）", 88),
    S.AWAITING_EFFECT_CONFIRM: ("awaiting_effect_confirm", "画好了，等您确认", 100),
    S.INTERRUPTED: ("interrupted", "服务重启了，任务已暂停", 0),
    S.FAILED: ("failed", "这次没画好", 100),
}

#: 可自动重试的上游错误（认证/额度类错误不重试，避免白烧钱）
RETRYABLE_CODES = {
    ErrorCode.UPSTREAM_TIMEOUT,
    ErrorCode.UPSTREAM_RATE_LIMITED,
    ErrorCode.UPSTREAM_ERROR,
    ErrorCode.GENERATE_FAILED,
    ErrorCode.GENERATE_TIMEOUT,
    ErrorCode.LLM_OUTPUT_INVALID,
    ErrorCode.VERIFY_FAILED,
    ErrorCode.IMAGE_SEARCH_FAILED,
}


class PipelineRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        backend: StorageBackend,
        task_store: TaskStore,
        asset_store: AssetStore,
        providers: ProviderBundle,
        styles: StyleRegistry,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.task_store = task_store
        self.asset_store = asset_store
        self.providers = providers
        self.styles = styles
        # 单进程后台 worker（串行）：
        # - 不依赖事件循环，因此在同步/异步路由里都能安全调度；
        # - max_workers=1 与 PRD “一次只生成一双”一致，任务状态已落盘，重启可恢复。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lvli-worker")

    # ------------------------------------------------------------------ 调度
    def submit(self, owner_id: str, task_id: str) -> None:
        """后台执行（立即返回，不阻塞 HTTP 请求；页面可继续浏览鞋柜）。"""
        self._executor.submit(self._run_guarded, owner_id, task_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def run_sync(self, owner_id: str, task_id: str) -> None:
        """同步执行（测试与 PIPELINE_INLINE=true 时使用）。"""
        self._run_guarded(owner_id, task_id)

    def _run_guarded(self, owner_id: str, task_id: str) -> None:
        try:
            self._run(owner_id, task_id)
        except AppError as exc:  # pragma: no cover - _run 内部已处理业务错误
            self._safe_fail(owner_id, task_id, exc)
        except Exception as exc:  # pragma: no cover - 兜底，绝不把堆栈丢给用户
            logger.exception("流水线未预期异常 task_id=%s", task_id)
            self._safe_fail(owner_id, task_id, AppError(ErrorCode.INTERNAL_ERROR, detail={"reason": type(exc).__name__}))

    # ------------------------------------------------------------------ 主流程
    def _run(self, owner_id: str, task_id: str) -> None:
        record = self.task_store.get(owner_id, task_id)
        if record.state in TERMINAL_STATES:
            return
        style = self.styles.get(record.style_id)
        trace = TraceWriter(self.backend, owner_id, task_id)
        recorder = CallRecorder(
            self.settings.task_max_upstream_calls,
            self.settings,
            used_calls=record.upstream_calls,
            used_cost=record.est_cost_cny,
        )

        model_only = bool(record.source.use_model_only)
        canvas_ready = bool(record.source.source_path) and self.asset_store.exists(record.source.source_path)

        # 阶段：源图准备（文搜图 + 排序 + 视觉预筛，线上约 58s）
        # 它原先在 POST /tasks 请求里串行跑，把请求拖到 60s+，超出前端 30s 超时；
        # 现在出现在这里：接口只做型号校对（~2s）就返回，后续交给流水线，前端轮询。
        if record.state == S.SEARCHING_SOURCE:
            self._prepare_source(record, recorder, trace)
            return

        if model_only:
            # 型号直出：候选图都不适合当参考时的兜底路径 —— 直接凭型号知识画线稿
            record.attempts.round = record.attempts.round + 1
            record.attempts.used_in_round = 0
            record.error = None
            trace.write("model_only_generation", model_name=record.resolve.normalized or record.query)
            self._set_state(
                record, S.GENERATING, "generate_round_start",
                {"round": record.attempts.round, "model_only": True}, recorder,
            )
        elif canvas_ready:
            record.attempts.round += 1
            record.attempts.used_in_round = 0
            record.error = None
            self._set_state(
                record, S.GENERATING, "generate_round_start", {"round": record.attempts.round}, recorder
            )
        else:
            record.attempts.round = 1 if record.attempts.round == 0 else record.attempts.round + 1
            record.attempts.used_in_round = 0
            record.error = None
            self._preprocess(record, style, trace)

        # 质检比对的参考图：正常路径用源图；型号直出时用搜到的最佳候选（可能没有）
        source_png: bytes | None
        canvas_png: bytes | None
        structure_png: bytes | None = None
        if model_only:
            canvas_png = None
            # 型号直出时**不拿那张不可用的搜图**当质检基准：
            # 拿它比对会把"鞋型不符"误判成模型的错（实测同一张图：拿坏图当基准 0.605/鞋型0.58，
            # 不拿图当基准 0.829/鞋型0.72）。此时让质检员按型号知识判断鞋型与 Logo。
            source_png = None
        else:
            source_png = self.asset_store.get_task_file(owner_id, task_id, SOURCE_FILENAME)
            canvas_png = self.asset_store.get(record.source.source_path)  # type: ignore[arg-type]
            if self.settings.enable_structure_reference:
                structure_key = self.asset_store.task_key(owner_id, task_id, EDGE_FILENAME)
                if self.asset_store.exists(structure_key):
                    structure_png = self.asset_store.get(structure_key)

        max_attempts = max(1, self.settings.gen_max_attempts)
        while record.attempts.used_in_round < max_attempts:
            record.attempts.used_in_round += 1
            record.attempts.total += 1
            attempt = record.attempts.total
            try:
                self._set_state(record, S.GENERATING, "generate_start", {"attempt": attempt}, recorder)
                raw = generate_lineart(
                    canvas_png,
                    style=style,
                    attempt=attempt,
                    generator=self.providers.generator,
                    recorder=recorder,
                    structure_reference=structure_png,
                    model_name=record.resolve.normalized or record.query,
                    logo_fill=record.inspect.logo_fill_hint if record.inspect else None,
                    shoe_texts=record.inspect.texts if record.inspect else None,
                    # 体检没看到品牌标识（或标记为"无需填实"）→ 明确禁止编造 Logo
                    avoid_logo=bool(
                        record.inspect
                        and (not record.inspect.logo_type or not record.inspect.logo_fill_required)
                    ),
                )
                self.asset_store.put_task_file(owner_id, task_id, f"raw_a{attempt}.png", raw)

                self._set_state(record, S.REFINING, "refine_start", {"attempt": attempt}, recorder)
                final, refine_meta = refine_lineart(
                    raw,
                    target_width=self.settings.artwork_width,
                    target_height=self.settings.artwork_height,
                )
                artwork_name = STAGING_ARTWORK_TEMPLATE.format(attempt=attempt)
                artwork_key = self.asset_store.put_task_file(owner_id, task_id, artwork_name, final)

                self._set_state(record, S.VERIFYING, "verify_start", {"attempt": attempt}, recorder)
                result = verify_lineart(
                    model_name=record.resolve.normalized or record.query,
                    style=style,
                    source_png=source_png,
                    artwork_png=final,
                    judge=self.providers.judge,
                    recorder=recorder,
                    settings=self.settings,
                )

                # 文字兜底贴合（决策记录九.⑧）：文字可辨度过低时，把原图裁出的文字贴到线稿
                if result.report.text_legible < self.settings.text_fallback_threshold:
                    stamps = self._load_text_stamps(owner_id, task_id, record.text_stamps)
                    if stamps:
                        final = composite_text_stamps(final, stamps)
                        self.asset_store.put_task_file(owner_id, task_id, artwork_name, final)
                        trace.write("text_stamp_applied", count=len(stamps), attempt=attempt)
            except AppError as exc:
                record.upstream_calls = recorder.total_calls
                record.est_cost_cny = recorder.total_cost
                trace.write("attempt_failed", attempt=attempt, code=exc.code.value)
                if exc.code in RETRYABLE_CODES and record.attempts.used_in_round < max_attempts:
                    self._save(record)
                    continue
                self._fail(record, exc, trace, recorder)
                return

            candidate = ArtworkCandidate(
                attempt=attempt,
                path=artwork_key,
                score=result.score,
                passed=result.passed,
                issues=result.issues,
                created_at=now_iso(),
            )
            record.artworks.append(candidate)
            best = max(record.artworks, key=lambda item: (item.score or 0.0))
            record.quality = QualityInfo(
                score=result.score,
                attempts=record.attempts.used_in_round,
                checks={
                    "shoe_silhouette_match": result.report.shoe_silhouette_match,
                    "logo_legibility": result.report.logo_legibility,
                    "style_consistency": result.report.style_consistency,
                    "noise_level": result.report.noise_level,
                    "canvas_ratio": result.artwork_check["canvas_score"],
                    "logo_filled": result.report.logo_filled,
                    "laces_solid_ratio": result.report.laces_solid_ratio,
                    "text_legible": result.report.text_legible,
                },
                issues=result.issues,
                verdict=result.report.verdict or ("pass" if result.passed else "fail"),
                best_attempt=best.attempt,
                artwork_check=result.artwork_check,
            )
            record.upstream_calls = recorder.total_calls
            record.est_cost_cny = recorder.total_cost
            trace.write(
                "verify_result",
                attempt=attempt,
                score=result.score,
                passed=result.passed,
                checks=record.quality.checks,
                issues=result.issues,
                refine=refine_meta,
                artwork_check=result.artwork_check,
            )
            hooks.run(
                "after_generate",
                {"owner_id": owner_id, "task_id": task_id, "attempt": attempt, "score": result.score},
            )
            self._save(record)

            if result.passed:
                self._set_state(
                    record,
                    S.AWAITING_EFFECT_CONFIRM,
                    "quality_passed",
                    {"attempt": attempt, "score": result.score},
                    recorder,
                )
                trace.write("done", attempt=attempt, score=result.score, upstream_calls=recorder.total_calls,
                            est_cost_cny=recorder.total_cost, calls=recorder.traces())
                return

            if record.attempts.used_in_round >= max_attempts:
                # 产品原则（2026-09-23 产品反馈）：**不要 dead-end**。
                # 只要画出了至少一张，就把它交给用户裁决（满意归档 / 重新画）——
                # 以前这里直接把任务判 failed，用户连图都看不到（而文案还写着"已交给您裁决"，自相矛盾）。
                # 真正无图可交（上游报错等）的情况依旧走 _fail。
                note = self._user_note(result)
                record.quality = record.quality.model_copy(update={"note": note})
                record.error = None
                trace.write(
                    "delivered_below_threshold",
                    attempt=best.attempt,
                    score=best.score,
                    style_blocked=result.style_blocked,
                    note=note,
                )
                self._set_state(
                    record,
                    S.AWAITING_EFFECT_CONFIRM,
                    "quality_below_threshold",
                    {"attempt": best.attempt, "score": best.score},
                    recorder,
                )
                return

    # ------------------------------------------------------------------ 步骤
    @staticmethod
    def _user_note(result) -> str:
        """给用户看的一句话：自检没完全通过（**不含质检细节** —— 产品反馈：细节不外显）。

        细节仍在 ``quality.issues`` / ``quality.checks`` 里，供后台排查与将来做统计。
        """
        if result.style_blocked:
            return "这张的线条风格没完全达到标准，您可以先收下，或再画一次。"
        return "这张没完全达到我们的标准，您可以先收下，或再画一次。"

    def _prepare_source(
        self, record: TaskRecord, recorder: CallRecorder, trace: TraceWriter
    ) -> None:
        """流水线阶段：文搜图 → 排序 → 视觉预筛 → 决定呈现方式。

        结果要么落到人工确认点（awaiting_source_confirm），
        要么落到 resolve_failed（搜图失败/空结果，用户可改用手动源图）。
        """
        self._set_state(record, S.SEARCHING_SOURCE, "search_start", {}, recorder)
        resolved = ModelResolveOut(
            normalized=record.resolve.normalized,
            brand=record.resolve.brand,
            confidence=record.resolve.confidence,
            exists=record.resolve.exists,
        )
        try:
            ranked, screen_summary, mode = prepare_source_candidates(
                resolved,
                settings=self.settings,
                search_provider=self.providers.search,
                judge=self.providers.judge,
                recorder=recorder,
                trace=trace,
            )
        except AppError as exc:
            record.error = TaskError(code=exc.code.value, message=exc.message, detail=exc.detail)
            record.upstream_calls = recorder.total_calls
            record.est_cost_cny = recorder.total_cost
            transit(record, S.RESOLVE_FAILED, event="search_failed", detail={"code": exc.code.value})
            record.progress = {"step": "resolve_failed", "label": "取图失败", "percent": 100}
            self._save(record)
            trace.write("search_failed", code=exc.code.value)
            return

        record.source = SourceInfo(
            candidates=ranked,
            mode=mode,
            recommended_index=0,
            screen=screen_summary,
        )
        trace.write(
            "search_result",
            found=len(ranked),
            provider=self.providers.search.name,
            mode=mode,
            screen=screen_summary,
            mode_reason=MODE_REASON.get(mode, ""),
        )
        self._set_state(
            record,
            S.AWAITING_SOURCE_CONFIRM,
            "source_candidates_ready",
            {"count": len(ranked), "mode": mode},
            recorder,
        )
        record.progress = {
            "step": "awaiting_source_confirm",
            "label": "请确认是这双吗",
            "percent": 20,
        }
        self._save(record)

    def _preprocess(self, record: TaskRecord, style: StyleTemplate, trace: TraceWriter) -> None:
        self._set_state(record, S.PREPROCESSING, "preprocess_start", {}, None)
        source_bytes = self.asset_store.get_task_file(
            record.owner_id, record.task_id, SOURCE_FILENAME
        )
        cutout, segment_meta = segment_shoe(source_bytes)
        self.asset_store.put_task_file(record.owner_id, record.task_id, CUTOUT_FILENAME, cutout)

        canvas, normalize_meta = normalize_view(
            cutout,
            width=self.settings.artwork_width,
            height=self.settings.artwork_height,
            padding_ratio=style.canvas.padding_ratio,
        )
        canvas_key = self.asset_store.put_task_file(
            record.owner_id, record.task_id, CANVAS_FILENAME, canvas
        )
        record.source.source_path = canvas_key

        # 文字兜底贴片：从原图裁出文字区域（决策记录九.⑧）—— 失败不致命，静默跳过
        record.text_stamps = self._build_text_stamps(record, source_bytes, canvas, normalize_meta)

        structure_key: str | None = None
        if self.settings.enable_structure_reference:
            edge_png, edge_meta = extract_edge_map(
                canvas, max_edge=self.settings.ark_max_image_edge
            )
            structure_key = self.asset_store.put_task_file(
                record.owner_id, record.task_id, EDGE_FILENAME, edge_png
            )
        else:
            edge_meta = {"skipped": True}

        trace.write(
            "preprocess",
            segment=segment_meta,
            normalize=normalize_meta,
            edge=edge_meta,
            structure_reference=bool(structure_key),
        )
        self._set_state(
            record,
            S.GENERATING,
            "preprocess_done",
            {"canvas": canvas_key, "structure_reference": bool(structure_key)},
            None,
        )

    def _build_text_stamps(
        self,
        record: TaskRecord,
        source_bytes: bytes,
        canvas: bytes,
        normalize_meta: dict,
    ) -> list[dict]:
        """把体检给的文字归一化 bbox 映射到画布坐标，并从画布裁出二值文字贴片。"""
        if not record.inspect or not record.inspect.text_stamps:
            return []
        bbox = normalize_meta.get("subject_bbox")
        scale = normalize_meta.get("scale")
        offset = normalize_meta.get("offset")
        if not bbox or scale is None or offset is None:
            return []

        with Image.open(io.BytesIO(source_bytes)) as source:
            cropped_size = (source.width, source.height)
        canvas_rgb = np.array(Image.open(io.BytesIO(canvas)).convert("RGB"))

        stamps: list[dict] = []
        for index, item in enumerate(record.inspect.text_stamps):
            if item.box is None or not item.text:
                continue
            stamp = build_text_stamp(
                canvas_rgb,
                box_norm=item.box,
                cropped_size=cropped_size,
                subject_bbox=tuple(bbox),
                scale=float(scale),
                offset=tuple(offset),
            )
            if stamp is None:
                continue
            name = f"text_stamp_{index}.png"
            self.asset_store.put_task_file(record.owner_id, record.task_id, name, stamp.png)
            stamps.append({"box": list(stamp.box), "path": name})
        return stamps

    def _load_text_stamps(self, owner_id: str, task_id: str, stamps_meta: list[dict]) -> list[TextStamp]:
        """从任务目录读回文字贴片（生成阶段用）。"""
        out: list[TextStamp] = []
        for meta in stamps_meta:
            path = meta.get("path")
            box = meta.get("box")
            if not path or not box:
                continue
            key = self.asset_store.task_key(owner_id, task_id, path)
            if not self.asset_store.exists(key):
                continue
            out.append(TextStamp(box=tuple(box), png=self.asset_store.get(key)))
        return out

    def _set_state(
        self,
        record: TaskRecord,
        target: TaskState,
        event: str,
        detail: dict | None = None,
        recorder: CallRecorder | None = None,
    ) -> None:
        transit(record, target, event=event, detail=detail)
        if target in PROGRESS:
            step, label, percent = PROGRESS[target]
            record.progress = {"step": step, "label": label, "percent": percent}
        if recorder is not None:
            record.upstream_calls = recorder.total_calls
            record.est_cost_cny = recorder.total_cost
        self._save(record)

    def _save(self, record: TaskRecord) -> None:
        self.task_store.save(record)

    def _fail(
        self,
        record: TaskRecord,
        error: AppError,
        trace: TraceWriter | None = None,
        recorder: CallRecorder | None = None,
    ) -> None:
        record.error = TaskError(code=error.code.value, message=error.message, detail=error.detail)
        if recorder is not None:
            record.upstream_calls = recorder.total_calls
            record.est_cost_cny = recorder.total_cost
        if record.artworks:
            best = max(record.artworks, key=lambda item: (item.score or 0.0))
            record.quality.best_attempt = best.attempt
        if record.state not in TERMINAL_STATES:
            try:
                transit(record, S.FAILED, event="failed", detail={"code": error.code.value})
            except AppError:
                record.state = S.FAILED
        record.progress = {"step": "failed", "label": PROGRESS[S.FAILED][1], "percent": 100}
        self._save(record)
        hooks.run("on_failure", {"owner_id": record.owner_id, "task_id": record.task_id,
                                 "code": error.code.value})
        if trace is not None:
            trace.write("failed", code=error.code.value, message=error.message,
                        upstream_calls=record.upstream_calls, est_cost_cny=record.est_cost_cny,
                        calls=recorder.traces() if recorder else [])
        logger.info("任务失败 task_id=%s code=%s", record.task_id, error.code.value)

    def _safe_fail(self, owner_id: str, task_id: str, error: AppError) -> None:
        try:
            record = self.task_store.get(owner_id, task_id)
        except AppError:
            return
        self._fail(record, error)
