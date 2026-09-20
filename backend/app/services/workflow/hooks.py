"""s04 钩子系统（轻量）：阶段回调，不污染主流程。

默认注册的钩子只做“写轨迹”，业务分支仍由状态机决定（避免钩子隐藏控制流）。
"""

from __future__ import annotations

from typing import Any, Callable

HookFn = Callable[[dict[str, Any]], None]

HOOK_NAMES = (
    "after_source_selected",
    "after_generate",
    "after_verify",
    "after_archive",
    "on_failure",
)

_hooks: dict[str, list[HookFn]] = {name: [] for name in HOOK_NAMES}


def register(name: str, fn: HookFn) -> None:
    _hooks.setdefault(name, []).append(fn)


def clear() -> None:
    for name in _hooks:
        _hooks[name].clear()


def run(name: str, context: dict[str, Any]) -> None:
    for fn in list(_hooks.get(name, [])):
        try:
            fn(context)
        except Exception:  # pragma: no cover - 钩子失败绝不影响主流程
            continue
