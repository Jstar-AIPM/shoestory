"""工具：归档进鞋柜（archive_shoe）。

- 画稿先经 export_asset 校验（3:2 / 白底 / 纯二值），不合格直接拦截
- `date_sort_key` 由确定性解析器生成（见 services/datetext.py）
- 写入走 ArchiveStore（原子写入 + 单写者锁）
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.idgen import new_shoe_id, now_iso
from app.schemas.archive import (
    ArchiveItem,
    ArchiveQuality,
    ArchiveSource,
    ArtworkMeta,
)
from app.schemas.enums import RIGHTS_NOTE
from app.services.datetext import parse_date_text
from app.services.storage.archive_store import ArchiveStore
from app.services.storage.asset_store import AssetStore
from app.services.style.loader import StyleTemplate
from app.services.tools.export_asset import export_asset


def archive_shoe(
    *,
    archive_store: ArchiveStore,
    asset_store: AssetStore,
    settings: Settings,
    owner_id: str,
    model_name: str,
    model_name_input: str,
    artwork_png: bytes,
    style: StyleTemplate,
    source: ArchiveSource,
    quality: ArchiveQuality,
    trace_id: str,
    date_text: str | None = None,
    story: str | None = None,
    manual_order: int | None = None,
) -> ArchiveItem:
    # 校验标准按风格走：黑白稿要求纯二值，水彩稿要求纸底留白（见 export_asset）
    exported, check = export_asset(artwork_png, settings, style)
    shoe_id = new_shoe_id()
    artwork_path = asset_store.put_archive_artwork(owner_id, shoe_id, exported)

    parse_result = parse_date_text(date_text)
    item = ArchiveItem(
        shoe_id=shoe_id,
        owner_id=owner_id,
        model_name=model_name,
        model_name_input=model_name_input,
        artwork_path=artwork_path,
        artwork_meta=ArtworkMeta(
            width=check["width"],
            height=check["height"],
            ratio="3:2",
            binary=bool(check["binary"]),
            background=check["background"],
            background_ratio=check.get("background_ratio"),
            has_text_overlay=False,
            white_ratio=check["white_ratio"],
        ),
        date_text=date_text or None,
        date_sort_key=parse_result.key,
        story=story or None,
        manual_order=manual_order,
        created_at=now_iso(),
        style_id=style.style_id,
        style_version=style.version,
        source=source,
        quality=quality,
        trace_id=trace_id,
        rights_note=RIGHTS_NOTE,
    )
    return archive_store.add(item)
