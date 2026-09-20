#!/usr/bin/env python
"""凭证体检：只报“有没有填 / 长度 / 是否粘错位置”，绝不打印 Key 本身。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402

CHECKS = [
    ("ARK_API_KEY", "方舟 API Key（模型调用）", "ark-"),
    ("ARK_TEXT_MODEL", "型号校对模型", "doubao-"),
    ("ARK_VISION_MODEL", "画稿质检模型", "doubao-"),
    ("ARK_IMAGE_MODEL", "图生图模型", "doubao-"),
    ("VOLC_SEARCH_API_KEY", "豆包搜索 API Key", None),
]


def main() -> int:
    settings = Settings()
    raw = (BACKEND_DIR.parent / ".env").read_text(encoding="utf-8")
    values = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()

    print(f"{'配置项':<22}{'状态':<10}{'长度':>6}  说明")
    print("-" * 72)
    problems: list[str] = []
    for key, label, prefix in CHECKS:
        value = values.get(key, "")
        if not value:
            print(f"{key:<22}{'未填':<10}{0:>6}  {label}")
            problems.append(key)
            continue
        note = label
        if prefix and not value.startswith(prefix) and key != "VOLC_SEARCH_API_KEY":
            note += "  ⚠️ 看起来不是该平台的 Key/模型名"
            problems.append(key)
        if key != "VOLC_SEARCH_API_KEY" and value.startswith("ark-") and "MODEL" in key:
            note += "  ⚠️ 这里应该填模型名，不是 API Key"
            problems.append(key)
        print(f"{key:<22}{'已填':<10}{len(value):>6}  {note}")

    print("-" * 72)
    print("当前上游模式：", "真实模型 ✅" if settings.real_mode_ready else "演示模式（mock）")
    print("搜图模式：", "真实（豆包搜索）✅" if settings.search_credentials_present else "mock（未填 Key）")
    if problems:
        print("待处理：", "、".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
