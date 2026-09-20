"""模型输出的宽容解析 + 强校验（手册 [A] “格式约束三件套”）。

1. Prompt 写正反例（见 prompts/*.md）
2. 解析器要宽容：兼容 ```json 包裹、前后解释文字、多个 JSON 混排（取第一个完整对象）
3. 数量/内容约束不遵守 != 解析错误：交给 Pydantic 校验，越界即拒绝并有限重试

绝不猜测模型意图：解析或校验失败 -> AppError(LLM_OUTPUT_INVALID)。
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError, ErrorCode

T = TypeVar("T", bound=BaseModel)


def _first_balanced_object(text: str) -> str | None:
    """扫描出第一个括号平衡的 JSON 对象（忽略字符串内的括号）。"""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        start = text.find("{", start + 1)
    return None


def parse_json_loose(text: str) -> dict[str, Any]:
    """从模型返回的文本里尽力取出一个 JSON 对象。"""
    if not text or not text.strip():
        raise AppError(ErrorCode.LLM_OUTPUT_INVALID, detail={"reason": "空响应"})

    candidates: list[str] = [text.strip()]
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        candidates.append("\n".join(lines).strip())
    balanced = _first_balanced_object(text)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise AppError(ErrorCode.LLM_OUTPUT_INVALID, detail={"reason": "未找到合法 JSON 对象"})


def validate_llm_output(model: type[T], text: str) -> T:
    """宽容解析 + Pydantic 强校验；失败一律 LLM_OUTPUT_INVALID（不含模型原文）。"""
    data = parse_json_loose(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise AppError(
            ErrorCode.LLM_OUTPUT_INVALID,
            detail={
                "reason": "结构校验失败",
                "field": ".".join(str(p) for p in first.get("loc", ())) or "?",
                "type": first.get("type", "unknown"),
            },
        ) from exc
