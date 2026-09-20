"""风格模板注册表：扫描 `styles/*.yaml`，按 style_id 注入。"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import AppError, ErrorCode
from app.services.style.loader import StyleTemplate, load_template


class StyleRegistry:
    def __init__(self, styles_dir: Path) -> None:
        self.styles_dir = Path(styles_dir)
        self._cache: dict[str, StyleTemplate] | None = None

    def reload(self) -> None:
        self._cache = None

    def _load_all(self) -> dict[str, StyleTemplate]:
        if self._cache is not None:
            return self._cache
        registry: dict[str, StyleTemplate] = {}
        if self.styles_dir.is_dir():
            for path in sorted(self.styles_dir.glob("*.yaml")):
                template = load_template(path)
                registry[template.style_id] = template
        self._cache = registry
        return registry

    def get(self, style_id: str) -> StyleTemplate:
        registry = self._load_all()
        if style_id not in registry:
            raise AppError(
                ErrorCode.STYLE_NOT_FOUND,
                detail={"style_id": style_id, "available": sorted(registry)},
            )
        return registry[style_id]

    def get_or_default(self, style_id: str | None, default_id: str) -> StyleTemplate:
        return self.get(style_id or default_id)

    def summaries(self) -> list[dict]:
        return [
            {
                "style_id": t.style_id,
                "name": t.name,
                "version": t.version,
                "canvas": {
                    "aspect_ratio": t.canvas.aspect_ratio,
                    "view": t.canvas.view,
                    "direction": t.canvas.direction,
                },
            }
            for t in sorted(self._load_all().values(), key=lambda x: x.style_id)
        ]
