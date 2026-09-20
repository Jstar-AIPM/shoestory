"""工具：型号校对（resolve_model）。

知识 ②「品牌型号图鉴」的阶段 1 最小形态：一份品牌名清单，用于给模型补充上下文、
并在质检/搜图 query 里保持品牌前缀一致。阶段 2 可扩展成结构化数据文件
（model -> 特征映射，用于 Logo 校验）。
"""

from __future__ import annotations

from app.schemas.llm import ModelResolveOut
from app.services.providers.base import CallRecorder, ModelResolver

#: 最小品牌图鉴（作为模型上下文；不用于编造型号）
KNOWN_BRANDS: list[str] = [
    "Nike",
    "Air Jordan",
    "adidas",
    "New Balance",
    "ASICS",
    "Converse",
    "Vans",
    "Puma",
    "Under Armour",
    "Reebok",
    "Salomon",
    "HOKA",
    "On",
    "Anta",
    "Li-Ning",
    "Peak",
    "361°",
]


def resolve_model(
    raw_query: str, resolver: ModelResolver, recorder: CallRecorder
) -> ModelResolveOut:
    """规范化用户输入的型号；匹配不到时返回 exists=false + 相近候选（绝不硬编）。"""
    return resolver.resolve(raw_query, KNOWN_BRANDS, recorder)
