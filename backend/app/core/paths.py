"""路径与文件安全：受控 key 解析、owner 校验、手动源图白名单（防路径遍历）。

底线（工程约定）：上传/指定文件必须检查格式、真实内容类型、大小与安全文件名，
防止路径遍历；所有 key 都必须是受控相对路径。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import AppError, ErrorCode

OWNER_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_TRAVERSAL_TOKENS = ("..", "~", "\\", "\x00")


def validate_owner_id(owner_id: str | None) -> str:
    """owner_id 只允许 [a-z0-9_-]{1,32}：禁止 / 与 ..，防跨租户越权。"""
    if not owner_id or not OWNER_ID_RE.match(owner_id):
        raise AppError(ErrorCode.UNSAFE_OWNER_ID, detail={"owner_id": redact_hint(owner_id)})
    return owner_id


def redact_hint(value: str | None) -> str:
    if not value:
        return ""
    return value[:12] + ("…" if len(value) > 12 else "")


def owner_prefix(owner_id: str) -> str:
    return f"owners/{validate_owner_id(owner_id)}"


def safe_key(key: str) -> str:
    """校验并归一化受控相对 key（禁止绝对路径与 ../）。"""
    if not key or not isinstance(key, str):
        raise AppError(ErrorCode.UNSAFE_PATH)
    candidate = key.strip().replace("//", "/")
    if candidate.startswith("/") or any(tok in candidate for tok in _TRAVERSAL_TOKENS):
        raise AppError(ErrorCode.UNSAFE_PATH, detail={"key": redact_hint(key)})
    if not _SAFE_KEY_RE.match(candidate):
        raise AppError(ErrorCode.UNSAFE_PATH, detail={"key": redact_hint(key)})
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if not parts:
        raise AppError(ErrorCode.UNSAFE_PATH)
    return "/".join(parts)


def join_key(*parts: str) -> str:
    return safe_key("/".join(p.strip("/") for p in parts if p))


def owner_key(owner_id: str, *parts: str) -> str:
    return join_key(owner_prefix(owner_id), *parts)


def validate_manual_path(raw_path: str, allowed_dirs: list[Path]) -> Path:
    """手动源图：必须是约定目录内的已存在普通文件，且解析后仍在目录内（防符号链接逃逸）。"""
    if not raw_path:
        raise AppError(ErrorCode.UNSAFE_PATH)
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()
    for allowed in allowed_dirs:
        allowed_resolved = allowed.resolve()
        try:
            p.relative_to(allowed_resolved)
        except ValueError:
            continue
        if not p.exists() or not p.is_file():
            raise AppError(ErrorCode.UNSAFE_PATH, detail={"reason": "文件不存在"})
        return p
    raise AppError(
        ErrorCode.UNSAFE_PATH,
        message="这个文件不在允许的目录内，请把图片放进 ./tmp/sources 或 ./data/inbox 后重试。",
        detail={"allowed_dirs": [str(d) for d in allowed_dirs]},
    )


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
