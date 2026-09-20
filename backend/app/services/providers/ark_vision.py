"""火山方舟 · 视觉理解模型：画稿独立质检（s17 verify_lineart）。

注意：判定归代码——模型只给 4 项分数（鞋型/Logo/风格/噪点），画布比例与阈值比较
由确定性代码完成（阶段文档 7.4）。
"""

from __future__ import annotations

from app.core.config import PROMPTS_DIR, Settings
from app.services.cv.imageio import prepare_for_vision
from app.core.errors import AppError, ErrorCode
from app.schemas.llm import QualityReportOut, SourceScreenOut
from app.services.parsers import validate_llm_output
from app.services.providers.ark_common import ArkClient
from app.services.providers.base import CallRecorder, timer
from app.services.style.loader import StyleTemplate

SYSTEM_FALLBACK = "你是严格的球鞋线稿质检员。只输出一个 JSON 对象，四项分数都要给。"


class ArkQualityJudge:
    name = "ark"
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.ark_vision_model
        self.client = ArkClient(settings)
        self.system_prompt = self._load_prompt()

    @staticmethod
    def _load_prompt() -> str:
        path = PROMPTS_DIR / "verify_lineart.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return SYSTEM_FALLBACK

    def judge(
        self,
        *,
        model_name: str,
        style: StyleTemplate,
        source_png: bytes | None,
        artwork_png: bytes,
        recorder: CallRecorder,
    ) -> QualityReportOut:
        if source_png is None:
            user = (
                f"型号：{model_name}\n"
                f"风格规则：{style.style_rules_text()}\n"
                "注意：本次**没有原鞋参考图**（图1 就是待检线稿）。请按你对这个型号的了解，"
                "判断鞋型与 Logo 是否符合该型号的真实特征，并逐项打分，只输出一个 JSON 对象。"
            )
            images = [("图1 待检线稿", prepare_for_vision(artwork_png, max_edge=self.settings.ark_max_image_edge))]
        else:
            user = (
                f"型号：{model_name}\n"
                f"风格规则：{style.style_rules_text()}\n"
                "图1 是原鞋参考图，图2 是待检线稿。请逐项打分并只输出一个 JSON 对象。"
            )
            images = [
                ("图1 原鞋参考图", prepare_for_vision(source_png, max_edge=self.settings.ark_max_image_edge)),
                ("图2 待检线稿", prepare_for_vision(artwork_png, max_edge=self.settings.ark_max_image_edge)),
            ]
        recorder.check("vision")
        with timer() as box:
            try:
                text = self.client.chat_text(
                    model=self.model,
                    system=self.system_prompt,
                    user=user,
                    images=images,
                    temperature=0.0,
                )
            except AppError as exc:
                recorder.record(
                    "vision",
                    provider=self.name,
                    model=self.model,
                    duration_ms=box["ms"],
                    ok=False,
                    error_code=exc.code.value,
                )
                raise
        recorder.record(
            "vision",
            provider=self.name,
            model=self.model,
            duration_ms=box["ms"],
            detail={"chars": len(text)},
        )
        return validate_llm_output(QualityReportOut, text)


    # ---------------- 候选源图可用性预筛 ----------------
    def _load_screen_prompt(self) -> str:
        path = PROMPTS_DIR / "screen_source_images.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover
            return "你是球鞋图片可用性审核员，只输出一个 JSON 对象。"

    def screen_sources(
        self,
        *,
        images: list[bytes],
        model_name: str,
        recorder: CallRecorder,
    ) -> SourceScreenOut:
        labelled = [
            (f"候选图 {index + 1}（index={index}）", prepare_for_vision(data, max_edge=self.settings.ark_max_image_edge))
            for index, data in enumerate(images)
        ]
        user = (
            f"型号：{model_name}\n共 {len(images)} 张候选图，请逐张按规则判断，"
            "并只输出一个 JSON 对象。"
        )
        recorder.check("vision")
        with timer() as box:
            try:
                text = self.client.chat_text(
                    model=self.model,
                    system=self._load_screen_prompt(),
                    user=user,
                    images=labelled,
                    temperature=0.0,
                )
            except AppError as exc:
                recorder.record(
                    "vision", provider=self.name, model=self.model, duration_ms=box["ms"],
                    ok=False, error_code=exc.code.value, detail={"task": "screen_sources"},
                )
                raise
        recorder.record(
            "vision",
            provider=self.name,
            model=self.model,
            duration_ms=box["ms"],
            detail={"task": "screen_sources", "candidates": len(images), "chars": len(text)},
        )
        return validate_llm_output(SourceScreenOut, text)
