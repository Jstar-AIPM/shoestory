"""从多轮生成里挑一张"最优稿"。

## 为什么要单独一个函数（2026-09-24）

线上出现过一个很难发现的错误：**用户归档到的是那张质检明确判过不合格的稿子。**

Nike Air Force 1 的任务里生成过两次：第 1 次和第 2 次的加权总分**完全相同（都是 0.9525）**，
但第 1 次 `passed=False`（勾没有填实），第 2 次 `passed=True`（勾填实了）。
原来的写法是：

    item = max(record.artworks, key=lambda a: (a.score or 0.0))

分数相同时 `max` 返回**先出现的那个**，于是留下了不合格的第 1 张 —— 而通过的那张被丢掉了。
用户看到"勾没填"，根因就在这里。

所以选稿的顺序必须是：**先看有没有通过质检，再看分数，最后才看先后**。
分数只反映"像不像"，"过没过"是另一回事，不能混在一起比。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def pick_best_artwork(artworks: Sequence[T]):
    """返回最优的一张；空列表返回 None。"""
    if not artworks:
        return None
    return max(
        artworks,
        key=lambda item: (
            bool(getattr(item, "passed", False)),  # ① 通过了就一定优先于没通过的
            getattr(item, "score", None) or 0.0,  # ② 同是通过/同是未通过时比分数
            getattr(item, "attempt", 0),  # ③ 仍相同则取更晚的一次（后一次通常更收敛）
        ),
    )
