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
        """读已有任务用：**允许拿到隐藏风格**（老档案还得按它渲染）。"""
        return self.get(style_id or default_id)

    def available_ids(self) -> list[str]:
        """对用户开放的风格（升序）。"""
        return sorted(k for k, t in self._load_all().items() if not t.hidden)

    def resolve_for_new_task(self, style_id: str | None, default_id: str) -> StyleTemplate:
        """建新任务用哪个风格。

        两条规则，都不含"静默替换"：

        1. **请求里显式给了 style_id → 照办；认不出来就报错**（这是 API 契约：
           传了不存在的风格却悄悄给你换一个，比报错更糟）。已隐藏的风格也照办 ——
           "隐藏"的含义是**不对外提供**（不出现在风格列表、界面上选不到），
           而不是"禁用"；将来重新启用线稿风格、以及测试与调试都要靠这条路径。
        2. **没显式给，就按配置的默认风格来**；只有默认 id 根本不存在时才兜底到
           第一个对外开放的风格 —— 防的是"线上环境变量拼错一个字母 → 表现为点生成没反应"。
           **默认风格即使已隐藏也照用**：不声不响把别人的配置改掉是坏设计
           （我第一版就是那么写的，结果测试夹具明明指定了黑白风格却被悄悄换成了水彩）。
        """
        requested = (style_id or "").strip()
        if requested:
            return self.get(requested)
        if (default_id or "").strip():
            try:
                return self.get(default_id.strip())
            except AppError:
                pass
        available = self.available_ids()
        if not available:
            raise AppError(ErrorCode.STYLE_NOT_FOUND, detail={"reason": "没有可用风格"})
        return self.get(available[0])

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
            if not t.hidden
        ]
