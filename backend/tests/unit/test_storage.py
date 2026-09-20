"""存储：原子写入、损坏备份、schema 版本、并发写入、排序规则。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.idgen import now_iso
from app.schemas.archive import ArchiveItem, ArtworkMeta
from app.services.storage.archive_store import ArchiveStore, archive_key, sort_items
from app.services.storage.atomic_io import read_json, write_json
from app.services.storage.local_backend import LocalBackend


def make_item(shoe_id: str, *, date_sort_key=None, created_at=None, manual_order=None) -> ArchiveItem:
    return ArchiveItem(
        shoe_id=shoe_id,
        owner_id="owner",
        model_name="Nike KD 12",
        artwork_path=f"owners/owner/assets/{shoe_id}/artwork.png",
        artwork_meta=ArtworkMeta(width=1536, height=1024),
        date_sort_key=date_sort_key,
        created_at=created_at or now_iso(),
        manual_order=manual_order,
    )


@pytest.fixture
def backend(tmp_path) -> LocalBackend:
    return LocalBackend(tmp_path / "data")


def test_atomic_write_and_read(backend: LocalBackend) -> None:
    write_json(backend, "owners/owner/archive.json", {"schema_version": 1, "items": []})
    payload, corrupted = read_json(backend, "owners/owner/archive.json")
    assert payload == {"schema_version": 1, "items": []}
    assert corrupted is False
    # 不留临时文件
    assert not [k for k in backend.list_keys("owners") if ".tmp-" in k]


def test_read_missing_returns_none(backend: LocalBackend) -> None:
    payload, corrupted = read_json(backend, "owners/nobody/archive.json")
    assert payload is None and corrupted is False


def test_corrupt_json_is_backed_up_and_flagged(backend: LocalBackend) -> None:
    backend.put_bytes(archive_key("owner"), b"{ this is not json")
    store = ArchiveStore(backend)
    items, corrupted = store.load("owner")
    assert items == []
    assert corrupted is True
    backups = [k for k in backend.list_keys("owners/owner") if ".corrupt-" in k]
    assert backups, "损坏文件必须被备份保留，不能直接删除"


def test_schema_too_new_is_rejected(backend: LocalBackend) -> None:
    write_json(backend, archive_key("owner"), {"schema_version": 99, "items": []})
    with pytest.raises(AppError) as excinfo:
        ArchiveStore(backend).load("owner")
    assert excinfo.value.code is ErrorCode.SCHEMA_TOO_NEW


def test_concurrent_adds_keep_all_items(backend: LocalBackend) -> None:
    store = ArchiveStore(backend)

    def add(index: int) -> None:
        store.add(make_item(f"sh_{index:04d}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(100)))

    items, corrupted = store.load("owner")
    assert corrupted is False
    assert len(items) == 100
    assert len({item.shoe_id for item in items}) == 100


def test_update_and_delete(backend: LocalBackend) -> None:
    store = ArchiveStore(backend)
    store.add(make_item("sh_a"))
    store.add(make_item("sh_b"))

    updated = store.update("owner", "sh_a", {"story": "陪我跑完第一个半马", "date_sort_key": "2020-01-01"})
    assert updated.story == "陪我跑完第一个半马"

    store.delete("owner", "sh_b")
    items, _ = store.load("owner")
    assert [item.shoe_id for item in items] == ["sh_a"]

    with pytest.raises(AppError) as excinfo:
        store.get("owner", "sh_b")
    assert excinfo.value.code is ErrorCode.ARCHIVE_NOT_FOUND


def test_owner_isolation_between_files(backend: LocalBackend) -> None:
    store = ArchiveStore(backend)
    store.add(make_item("sh_a"))
    item_b = make_item("sh_b")
    item_b.owner_id = "owner_b"
    item_b.artwork_path = "owners/owner_b/assets/sh_b/artwork.png"
    store.add(item_b)

    owner_a_items, _ = store.load("owner")
    owner_b_items, _ = store.load("owner_b")
    assert [i.shoe_id for i in owner_a_items] == ["sh_a"]
    assert [i.shoe_id for i in owner_b_items] == ["sh_b"]


def test_sort_rules_null_last_and_created_tiebreak() -> None:
    items = [
        make_item("sh_none_1", date_sort_key=None, created_at="2024-01-01T00:00:00+08:00"),
        make_item("sh_2021", date_sort_key="2021-01-01", created_at="2024-02-01T00:00:00+08:00"),
        make_item("sh_2019", date_sort_key="2019-01-01", created_at="2024-03-01T00:00:00+08:00"),
        make_item("sh_none_0", date_sort_key=None, created_at="2020-01-01T00:00:00+08:00"),
    ]
    ordered = [item.shoe_id for item in sort_items(items, "date")]
    assert ordered == ["sh_2019", "sh_2021", "sh_none_0", "sh_none_1"]

    by_created = [item.shoe_id for item in sort_items(items, "created")]
    assert by_created == ["sh_none_0", "sh_none_1", "sh_2021", "sh_2019"]


def test_manual_order_has_highest_priority() -> None:
    items = [
        make_item("sh_a", date_sort_key="2019-01-01"),
        make_item("sh_pinned", date_sort_key="2024-01-01", manual_order=1),
    ]
    ordered = [item.shoe_id for item in sort_items(items, "date")]
    assert ordered == ["sh_pinned", "sh_a"]


def test_artwork_path_must_match_owner() -> None:
    payload = {
        "shoe_id": "sh_x",
        "owner_id": "owner",
        "model_name": "Nike KD 12",
        "artwork_path": "owners/someone_else/assets/sh_x/artwork.png",
        "artwork_meta": {"width": 1536, "height": 1024},
        "created_at": now_iso(),
    }
    with pytest.raises(Exception):
        ArchiveItem.model_validate(payload)


def test_backend_rejects_traversal_keys(backend: LocalBackend) -> None:
    with pytest.raises(AppError) as excinfo:
        backend.put_bytes("../../etc/passwd", b"x")
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_json_roundtrip_is_human_readable(backend: LocalBackend) -> None:
    backend.put_bytes("owners/owner/archive.json", json.dumps({"a": 1}, ensure_ascii=False).encode())
    assert b'"a": 1' in backend.get_bytes("owners/owner/archive.json")
