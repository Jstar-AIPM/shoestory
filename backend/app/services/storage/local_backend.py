"""本地文件系统后端：key -> data/ 下的受控路径。

写入纪律：临时文件 -> fsync -> os.replace（原子替换），避免半截文件。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.core.errors import AppError, ErrorCode
from app.core.paths import safe_key
from app.services.storage.backend import KeyNotFound


class LocalBackend:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------- 内部 ----------------
    def path_for(self, key: str) -> Path:
        normalized = safe_key(key)
        target = (self.root / normalized).resolve()
        # 双保险：解析后必须仍在 root 内（防符号链接逃逸）
        try:
            target.relative_to(self.root.resolve())
        except ValueError as exc:  # pragma: no cover - safe_key 已拦一层
            raise AppError(ErrorCode.UNSAFE_PATH) from exc
        return target

    # ---------------- 协议 ----------------
    def put_bytes(self, key: str, data: bytes) -> None:
        target = self.path_for(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, target)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except AppError:
            raise
        except OSError as exc:
            raise AppError(
                ErrorCode.STORAGE_WRITE_FAILED,
                detail={"key": key, "reason": type(exc).__name__},
            ) from exc

    def get_bytes(self, key: str) -> bytes:
        target = self.path_for(key)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise KeyNotFound(key) from exc

    def exists(self, key: str) -> bool:
        return self.path_for(key).exists()

    def delete(self, key: str) -> bool:
        target = self.path_for(key)
        if target.is_file():
            target.unlink()
            return True
        return False

    def rename(self, key: str, new_key: str) -> bool:
        src = self.path_for(key)
        dst = self.path_for(new_key)
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return True

    def delete_prefix(self, prefix: str) -> int:
        target = self.path_for(prefix)
        removed = 0
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                    removed += 1
                elif child.is_dir():
                    child.rmdir()
            target.rmdir()
        elif target.is_file():
            target.unlink()
            removed = 1
        return removed

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self.path_for(prefix) if prefix else self.root
        if base.is_file():
            return [str(base.relative_to(self.root))]
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())
