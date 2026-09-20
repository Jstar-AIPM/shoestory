"""流水线执行器（s11 后台任务 + s16 工作流运行时）。

形态固定，由代码状态机驱动：
  预处理(去背景 -> 3:2 白底画布) -> [生成 -> 后处理 -> 质检] 循环（上限 3 次/轮）
  -> 达标则 awaiting_effect_confirm（人工确认点，持久化）

- 每步都落盘（任务文件 + trace JSONL），进程重启后可恢复；
- 上游调用统一走 CallRecorder（成本护栏，硬上限 10 次/任务）；
- 不做开放式 Agent Loop（内部工程笔记 4.4）。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.schemas.enums import STAGING_ARTWORK_TEMPLATE, TaskState
from app.schemas.task import ArtworkCandidate, QualityInfo, TaskError, TaskRecord
from app.services.providers.base import CallRecorder, ProviderBundle
from app.services.storage.asset_store import AssetStore
from app.services.storage.backend import StorageBackend
from app.services.storage.task_store import TERMINAL_STATES, TaskStore
from app.services.style.loader import StyleTemplate
from app.services.style.registry import StyleRegistry
from app.services.cv.edges import extract_edge_map
from app.services.tools.generate_lineart import generate_lineart
from app.services.tools.normalize_view import normalize_view
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
    S.PREPROCESSING: ("preprocessing", "去背景 + 校正到 3:2 画布", 15),
    S.GENERATING: ("generating", "生成黑白线稿", 45),
    S.REFINING: ("refining", "后处理：二值化 + 去噪", 72),
    S.VERIFYING: ("verifying", "独立质检中", 88),
    S.AWAITING_EFFECT_CONFIRM: ("awaiting_effect_confirm", "出图完成，请确认", 100),
    S.INTERRUPTED: ("interrupted", "服务重启，已暂停", 0),
    S.FAILED: ("failed", "生成失败", 100),
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
                style_blocked = not result.style_ok
                self._fail(
                    record,
                    AppError(
                        ErrorCode.VERIFY_FAILED,
                        message=(
                            "这张参考图可能不适合做线稿（例如是两只鞋的合影、角度不是正侧面、"
                            "或本身就是深色鞋）——建议换一张候选图再试。"
                            if style_blocked
                            else (
                                f"连续 {max_attempts} 次质检都没通过，已把最接近的一张交给你裁决。"
                                f"原因：{'；'.join(result.issues[:2]) or '内容质量未达标准'}"
                            )
                        ),
                        detail={
                            "issues": result.issues,
                            "best_attempt": best.attempt,
                            "style_ok": result.style_ok,
                            "style_metrics": result.style_metrics,
                            "suggestion": "换一张候选参考图" if style_blocked else None,
                        },
                    ),
                    trace,
                    recorder,
                )
                return

    # ------------------------------------------------------------------ 步骤
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
