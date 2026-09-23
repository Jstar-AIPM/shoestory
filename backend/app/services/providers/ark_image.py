"""火山方舟 · Seedream 图生图：把标准画布转成黑白线稿。

参数全部来自风格模板（prompt.provider_params），代码不硬编码模型名与尺寸。
重试策略：按 attempt 微调 seed 并追加“更严格的约束句”，便于第二次/第三次收敛。
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError
from app.services.cv.imageio import prepare_for_vision
from app.services.providers.ark_common import ArkClient
from app.services.providers.base import CallRecorder, timer
from app.services.style.loader import StyleTemplate

RETRY_REINFORCEMENT = (
    "\n额外要求（本次必须更严格）：只保留黑色描边与白色底色，禁止任何灰阶像素；"
    "禁止排线/交叉影线/素描涂抹；"
    "Logo（钩形 / 交叉条纹 / 飞人 / 三道杠）必须用**纯黑实心块填充**，不要只画空心轮廓，"
    "形状必须清晰准确、不得简化变形；"
    "严格按参考图的轮廓描摹，不得改变鞋型。"
)


def _draw_hints_suffix(
    logo_fill: str | None, shoe_texts: list[str] | None, *, avoid_logo: bool = False
) -> str:
    """把「Logo 填色 + 鞋身文字 + 填色边界」追加进正向提示词。

    与质检闸门（logo_filled / laces_solid_ratio / text_legible）呼应：
    - Logo 标志性图形 → 纯黑实心填充（硬性）；
    - 鞋身文字 → 尽力还原，但「宁缺勿错」（写错的字母比不写更伤纪念档案可信度）；
    - 填色边界 → 只许填实小元素（Logo/鞋眼孔/透气孔），鞋带/中底/鞋面必须用轮廓线。

    ⚠️ 2026-09-23 线上实测（AJ36）：照片那个角度看不到飞人 Logo，模型于是**编了一个装饰性符号**，
    质检正确地判它"Logo 不对" → 整单失败、白烧两次生成。
    所以 logo_fill 与 avoid_logo 必须二选一：原图看得见才要求填，看不见就明确禁止编造。
    """
    parts: list[str] = []
    if logo_fill:
        parts.append(
            f"\n【Logo 填色】把「{logo_fill}」用纯黑实心块填充，不要只画空心轮廓，"
            "形状必须清晰准确、不得简化变形；"
            "**只画原图里确实能看到的那一处标识**，不得添加原图里没有的品牌标识。"
        )
    elif avoid_logo:
        parts.append(
            "\n【不要编造 Logo】这张原图的角度看不到明确的品牌标识："
            "请**不要**凭空添加任何品牌 Logo（钩形/飞人/三道杠等），也不要用无穷符号、"
            "装饰图形等代替；那个位置按原鞋的结构线如实表达即可。"
        )
    if shoe_texts:
        joined = "」「".join(shoe_texts)
        parts.append(
            f"\n【鞋身文字】在鞋身对应位置清晰写出「{joined}」。"
            "如果无法保证字母拼写正确，宁可省略该文字，也不要写错。"
        )
    if parts:
        parts.append(
            "\n【填色边界】只允许填实 Logo、鞋眼孔、透气孔等小元素；"
            "鞋带、中底、鞋面必须用轮廓线/结构线表达，不得填成实心块。"
        )
    return "".join(parts)


class ArkLineartGenerator:
    name = "ark"
    mode = "real"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.ark_image_model
        self.client = ArkClient(settings)

    def generate(
        self,
        *,
        canvas_png: bytes | None,
        style: StyleTemplate,
        attempt: int,
        recorder: CallRecorder,
        structure_reference: bytes | None = None,
        model_name: str | None = None,
        logo_fill: str | None = None,
        shoe_texts: list[str] | None = None,
        avoid_logo: bool = False,
    ) -> bytes:
        params = style.provider_params or {}
        size = str(params.get("size") or f"{self.settings.artwork_width}x{self.settings.artwork_height}")
        positive = style.prompt.positive.strip()
        if model_name:
            positive += (
                f"\n【画的款式】{model_name}。必须严格忠于这只鞋的实际款式与结构，"
                "不得替换成同品牌的其他型号、不得凭想象增删部件。"
            )
        positive += _draw_hints_suffix(logo_fill, shoe_texts, avoid_logo=avoid_logo)
        if canvas_png is None:
            positive += (
                "\n【本次没有参考照片】请依据你对这款鞋的了解，画出它的正侧面线稿，"
                "鞋型结构必须符合该型号的真实特征。"
            )
        if structure_reference is not None:
            positive += (
                "\n【参考图说明】第 1 张是实物照片，第 2 张是同一双鞋的边缘骨架图。"
                "请严格按骨架图的轮廓与结构描摹，只做线稿化处理，不得改变鞋型、不得增减部件。"
            )
        if attempt > 1:
            positive += RETRY_REINFORCEMENT
        seed = params.get("seed")
        if isinstance(seed, int):
            seed = seed + (attempt - 1)
        elif attempt > 1:
            seed = 1000 + attempt
        else:
            seed = None

        references = [structure_reference] if structure_reference is not None else []
        # 参考图先降采样：实测原图 1.5MP 的 PNG 会让请求体到 MB 级，拖慢上传与推理
        prepared_canvas = (
            prepare_for_vision(canvas_png, max_edge=self.settings.image_reference_max_edge, quality=92)
            if canvas_png is not None
            else None
        )

        recorder.check("image")
        with timer() as box:
            try:
                data = self.client.generate_image(
                    model=self.model,
                    prompt=positive,
                    negative_prompt=style.prompt.negative.strip(),
                    size=size,
                    image=prepared_canvas,
                    reference_images=references,
                    seed=seed,
                    guidance_scale=params.get("guidance_scale"),
                    prompt_optimize_mode=params.get("prompt_optimize_mode")
                    or self.settings.image_prompt_optimize_mode,
                )
            except AppError as exc:
                recorder.record(
                    "image",
                    provider=self.name,
                    model=self.model,
                    duration_ms=box["ms"],
                    ok=False,
                    error_code=exc.code.value,
                    detail={"attempt": attempt},
                )
                raise
        recorder.record(
            "image",
            provider=self.name,
            model=self.model,
            duration_ms=box["ms"],
            detail={
                "attempt": attempt,
                "size": size,
                "bytes": len(data),
                "references": 1 + len(references),
                "reference_kb": (len(prepared_canvas) // 1024) if prepared_canvas else 0,
                "prompt_optimize": params.get("prompt_optimize_mode")
                or self.settings.image_prompt_optimize_mode,
            },
        )
        return data
