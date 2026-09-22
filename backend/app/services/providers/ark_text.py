"""火山方舟 · 文本模型：型号校对（resolve_model）。

Prompt 从 `prompts/resolve_model.md` 读取（手册 [A]：Prompt 独立管理、可版本追踪）。
格式不合规时**最多再试 1 次**（阶段文档 3.3：每双鞋最多 2 次文本调用）。
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.schemas.llm import ModelResolveOut
from app.services.parsers import validate_llm_output
from app.services.prompts.loader import load_prompt_text
from app.services.providers.ark_common import ArkClient
from app.services.providers.base import CallRecorder, timer

SYSTEM_FALLBACK = "你是球鞋型号校对员。只输出一个 JSON 对象，不要任何解释。"


class ArkModelResolver:
    name = "ark"
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.ark_text_model
        self.client = ArkClient(settings)
        self.system_prompt = self._load_prompt()

    @staticmethod
    def _load_prompt() -> str:
        # 缺文件时会记 ERROR 并进入健康检查的 missing_prompts（线上事故复盘：不许静默降级）
        return load_prompt_text("resolve_model.md", SYSTEM_FALLBACK)

    def resolve(self, raw_query: str, known_brands: list[str], recorder: CallRecorder) -> ModelResolveOut:
        user = (
            f"用户输入：{raw_query}\n"
            f"已知品牌：{'、'.join(known_brands) if known_brands else '（无）'}\n"
            "请按要求只输出一个 JSON 对象。"
        )
        last_error: AppError | None = None
        for attempt in range(1, 3):  # 首次 + 1 次格式重试
            recorder.check("text")
            with timer() as box:
                try:
                    text = self.client.chat_text(
                        model=self.model, system=self.system_prompt, user=user, temperature=0.1
                    )
                except AppError as exc:
                    recorder.record(
                        "text",
                        provider=self.name,
                        model=self.model,
                        duration_ms=box["ms"],
                        ok=False,
                        error_code=exc.code.value,
                    )
                    raise
            recorder.record(
                "text",
                provider=self.name,
                model=self.model,
                duration_ms=box["ms"],
                detail={"attempt": attempt, "chars": len(text)},
            )
            try:
                return validate_llm_output(ModelResolveOut, text)
            except AppError as exc:
                last_error = exc
                user += (
                    "\n\n上次输出不符合要求（结构校验失败）。请严格只输出一个合法 JSON 对象，"
                    "字段：normalized, brand, confidence, exists, candidates, note。"
                )
        raise last_error or AppError(ErrorCode.LLM_OUTPUT_INVALID)
