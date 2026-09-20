"""ID 生成：shoe_id / task_id / trace_id 一律使用文件名安全字符集。"""

from __future__ import annotations

import secrets
from datetime import datetime


def _ts() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def _rand(n: int = 4) -> str:
    return secrets.token_hex(8)[:n]


def new_id(prefix: str) -> str:
    return f"{prefix}_{_ts()}_{_rand()}"


def new_task_id() -> str:
    return new_id("tk")


def new_shoe_id() -> str:
    return new_id("sh")


def new_trace_id() -> str:
    return new_id("tr")


def now_iso() -> str:
    """本地时间 ISO8601（带时区）：ISO8601 带时区（本地 +08:00）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")
