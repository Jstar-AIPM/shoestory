"""结构化日志（JSONL）+ 密钥脱敏。

底线要求：
- 日志中不得出现密钥、密码、用户故事全文；
- 只记元信息（模型、耗时、张数/字符数、错误类型、质检分数）。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_SECRETS: list[str] = []
_JSONL_PATH: Path | None = None


def redact(text: str) -> str:
    """抹掉已登记的敏感值（用于任何写日志/写轨迹的字符串）。"""
    if not text:
        return text
    out = text
    for secret in _SECRETS:
        if secret and secret in out:
            out = out.replace(secret, "***")
    return out


_SECRET_PATTERNS = (
    re.compile(r"ark-[0-9a-fA-F-]{16,}"),  # 火山方舟 API Key 的典型形状
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # 其他平台常见形状
    # 通用兜底：20 位以上、只由字母数字组成、且大小写混合（API Key 的常见形状）。
    # 模型名/URL/路径都含 - . / : 等分隔符，不会被误伤。
    re.compile(r"^(?=.*[a-z])(?=.*[A-Z])[A-Za-z0-9]{20,}$"),
)


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    """把任意“看起来像密钥”的值变成掩码，用于诊断输出。

    教训：诊断脚本打印“模型配置项”时，如果用户误把 Key 填到那里，就会把密钥打出来。
    因此凡是回显配置的地方一律过这个函数。
    """
    if not value:
        return "（空）"
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            head = value[:keep]
            tail = value[-keep:] if len(value) > keep * 2 else ""
            return f"{head}…{tail}（疑似密钥，已掩码）"
    return value


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            try:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args  # type: ignore[assignment]
                )
            except Exception:  # pragma: no cover - 防御性
                pass
        return True


class _JsonlHandler(logging.Handler):
    """把日志按行写成 JSONL，便于阶段 2 做观测看板。"""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - 直接读文件断言
        try:
            payload = {
                "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "logger": record.name,
                "msg": redact(record.getMessage()),
            }
            for key in ("event", "task_id", "owner_id", "step", "duration_ms"):
                value = getattr(record, key, None)
                if value is not None:
                    payload[key] = value
            fields = getattr(record, "fields", None)
            if isinstance(fields, dict):
                payload["fields"] = {
                    k: (redact(v) if isinstance(v, str) else v) for k, v in fields.items()
                }
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            with _LOCK:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
        except Exception:  # pragma: no cover - 日志失败不影响业务
            pass


def setup_logging(log_path: Path, *, level: str = "INFO", secrets: list[str] | None = None) -> None:
    global _JSONL_PATH
    _SECRETS.clear()
    _SECRETS.extend(secrets or [])

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_lvli", False):
            root.removeHandler(handler)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(_RedactionFilter())
    console._lvli = True  # type: ignore[attr-defined]

    jsonl = _JsonlHandler(log_path)
    jsonl.addFilter(_RedactionFilter())
    jsonl._lvli = True  # type: ignore[attr-defined]

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(console)
    root.addHandler(jsonl)
    _JSONL_PATH = log_path


def log_jsonl_path() -> Path | None:
    return _JSONL_PATH


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """记一条结构化事件（字段自动脱敏）。"""
    safe = {
        k: (redact(v) if isinstance(v, str) else v)
        for k, v in fields.items()
        if k not in {"story", "api_key", "password"}
    }
    # 用户故事只记长度，不记内容
    if "story" in fields:
        safe["story_len"] = len(fields["story"] or "")
    logger.info(
        "%s %s",
        event,
        json.dumps(safe, ensure_ascii=False, default=str),
        extra={"event": event, "fields": safe},
    )
