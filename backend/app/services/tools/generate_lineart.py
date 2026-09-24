"""工具：图生图生成线稿（generate_lineart）。

参数全部来自风格模板；生成失败按错误码交由状态机决定“重试”或“交用户裁决”。
启动 structure_reference（边缘骨架图）后，会作为第二张参考图一起传给模型，
用于“锁结构、防止自由创作”（等效 ControlNet 边缘引导）。
"""

from __future__ import annotations

from app.services.providers.base import CallRecorder, LineartGenerator
from app.services.style.loader import StyleTemplate


def generate_lineart(
    canvas_bytes: bytes | None,
    *,
    style: StyleTemplate,
    attempt: int,
    generator: LineartGenerator,
    recorder: CallRecorder,
    structure_reference: bytes | None = None,
    model_name: str | None = None,
    logo_fill: str | None = None,
    shoe_texts: list[str] | None = None,
    avoid_logo: bool = False,
    partial_logo: bool = False,
    emphasis: str | None = None,
) -> bytes:
    return generator.generate(
        canvas_png=canvas_bytes,
        style=style,
        attempt=attempt,
        recorder=recorder,
        structure_reference=structure_reference,
        model_name=model_name,
        logo_fill=logo_fill,
        shoe_texts=shoe_texts,
        avoid_logo=avoid_logo,
        partial_logo=partial_logo,
        emphasis=emphasis,
    )
