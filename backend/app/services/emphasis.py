"""重新生成的"定向强化句"：读 `prompts/emphasis.yaml`，供两处使用。

1. **用户选的**（`manual: true`）：界面上给几个选项（配色不对 / 鞋型不太像 / …），
   用户选一个 → 这里给出对应的强化句。每次重画都花 1 次额度，
   让用户把方向说清楚，比"换个种子再抽一次"有效得多。
2. **系统判的**（`manual: false`）：质检的确定性闸门给出失败原因
   （太轻 / 太重 / 轮廓崩）→ 自动重画时带上对应强化句。

为什么不放代码里写死：强化句是提示词资产，改它不该动代码；
而且它必须能被启动检查看见（缺文件 = 少一层纠错能力，不能静默降级）。
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from app.core.config import PROMPTS_DIR

EMPHASIS_FILE = "emphasis.yaml"


@dataclass(frozen=True)
class Emphasis:
    key: str
    text: str
    #: 是否作为"用户可选"的选项出现在界面上
    manual: bool
    #: 界面上的按钮文案（manual=True 时才有）
    label: str = ""


def _load() -> dict[str, Emphasis]:
    try:
        raw = yaml.safe_load((PROMPTS_DIR / EMPHASIS_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        # 缺文件不致命：退化成"没有定向强化"，由调用方决定怎么兜底
        return {}
    out: dict[str, Emphasis] = {}
    for key, spec in (raw.get("items") or {}).items():
        if not isinstance(spec, dict):
            continue
        text = str(spec.get("text") or "").strip()
        if not text:
            continue
        out[str(key)] = Emphasis(
            key=str(key),
            text=text,
            manual=bool(spec.get("manual", False)),
            label=str(spec.get("label") or "").strip(),
        )
    return out


def emphasis_text(key: str | None) -> str:
    """取强化句；未知 key 返回空串（**不抛异常** —— 强化句缺失不该让生成失败）。"""
    if not key:
        return ""
    item = _load().get(key)
    return item.text if item else ""


def manual_options() -> list[dict[str, str]]:
    """给界面的可选项（只含 manual=True 的，按 YAML 顺序）。"""
    return [
        {"key": item.key, "label": item.label or item.key}
        for item in _load().values()
        if item.manual and item.label
    ]


def is_valid(key: str) -> bool:
    return key in _load()
