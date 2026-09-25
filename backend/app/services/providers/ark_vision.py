"""火山方舟 · 视觉理解模型：画稿独立质检（s17 verify_lineart）。

注意：判定归代码——模型只给 4 项分数（鞋型/Logo/风格/噪点），画布比例与阈值比较
由确定性代码完成。
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.cv.imageio import prepare_for_vision
from app.core.errors import AppError, ErrorCode
from app.schemas.inspect import PhotoInspectOut
from app.schemas.llm import QualityReportOut, SourceScreenOut
from app.services.parsers import validate_llm_output
from app.services.prompts.loader import load_prompt_text
from app.services.providers.ark_common import ArkClient
from app.services.providers.base import CallRecorder, timer
from app.services.style.loader import StyleTemplate

SYSTEM_FALLBACK = "你是严格的球鞋线稿质检员。只输出一个 JSON 对象，四项分数都要给。"
SCREEN_FALLBACK = "你是球鞋图片可用性审核员，只输出一个 JSON 对象。"
INSPECT_FALLBACK = "你是球鞋图片审核员：判断图里是不是运动鞋，并识别品牌、型号、Logo 与鞋身文字；只输出一个 JSON 对象。"


class ArkQualityJudge:
    name = "ark"
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.ark_vision_model
        self.client = ArkClient(settings)
        #: 按文件名缓存：不同风格用不同的判官提示词（黑白 vs 水彩的"合格"标准不一样）
        self._prompt_cache: dict[str, str] = {}

    def _load_prompt(self, name: str) -> str:
        # 质检提示词缺失 = 质检闸门失效（比报错更危险），必须能在日志/健康检查里看见
        if name not in self._prompt_cache:
            self._prompt_cache[name] = load_prompt_text(name, SYSTEM_FALLBACK)
        return self._prompt_cache[name]

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
                    system=self._load_prompt(style.judge_prompt),
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
        # 同 _load_prompt：缺失会记 ERROR 并进入健康检查的 missing_prompts
        return load_prompt_text("screen_source_images.md", SCREEN_FALLBACK)

    def _load_inspect_prompt(self) -> str:
        # 缺失会记 ERROR 并进入健康检查的 missing_prompts
        return load_prompt_text("inspect_photo.md", INSPECT_FALLBACK)

    def inspect_photo(self, *, image: bytes, recorder: CallRecorder) -> PhotoInspectOut:
        """上传图体检：一次调用判断「是否鞋 / 鞋的数量 / 品牌型号 / Logo / 文字」。

        与 screen_sources 的区别：这里判的是"用户上传的图能不能用来画"，
        并顺带产出绘制所需的信息（Logo 填色要求、文字清单、归档标题）。
        """
        prepared = prepare_for_vision(image, max_edge=self.settings.ark_max_image_edge)
        user = (
            "这是用户上传的图片（可能截取自球鞋 App 的商品页）。"
            "请按要求判断并只输出一个 JSON 对象。"
        )
        recorder.check("vision")
        with timer() as box:
            try:
                text = self.client.chat_text(
                    model=self.model,
                    system=self._load_inspect_prompt(),
                    user=user,
                    images=[("用户上传图", prepared)],
                    temperature=0.0,
                )
            except AppError as exc:
                recorder.record(
                    "vision", provider=self.name, model=self.model, duration_ms=box["ms"],
                    ok=False, error_code=exc.code.value, detail={"task": "inspect_photo"},
                )
                raise
        recorder.record(
            "vision", provider=self.name, model=self.model, duration_ms=box["ms"],
            detail={"task": "inspect_photo", "chars": len(text)},
        )
        return validate_llm_output(PhotoInspectOut, text)

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
