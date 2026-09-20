"""路径与文件安全：路径遍历、符号链接逃逸、伪装图片、超大文件、owner 越权。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.paths import owner_key, safe_key, validate_manual_path, validate_owner_id
from app.services.cv.imageio import MAX_IMAGE_BYTES, validate_image_bytes
from tests.conftest import make_png_bytes


@pytest.mark.parametrize("bad", ["../evil", "a/b", "..", "", "A" * 40, "Owner!", "owner id"])
def test_invalid_owner_ids_rejected(bad: str) -> None:
    with pytest.raises(AppError) as excinfo:
        validate_owner_id(bad)
    assert excinfo.value.code is ErrorCode.UNSAFE_OWNER_ID


def test_valid_owner_id_and_key() -> None:
    assert validate_owner_id("owner_a-1") == "owner_a-1"
    assert owner_key("owner", "tasks", "tk_1.json") == "owners/owner/tasks/tk_1.json"


@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "../../etc/passwd", "owners/../../x", "a\\b", "owners/owner/./../x", "with space.txt"],
)
def test_unsafe_keys_rejected(bad: str) -> None:
    with pytest.raises(AppError) as excinfo:
        safe_key(bad)
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_manual_path_traversal_rejected(tmp_path) -> None:
    allowed = tmp_path / "sources"
    allowed.mkdir()
    with pytest.raises(AppError) as excinfo:
        validate_manual_path("../../etc/passwd", [allowed])
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_manual_path_outside_allowed_dir_rejected(tmp_path) -> None:
    allowed = tmp_path / "sources"
    allowed.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(make_png_bytes())
    with pytest.raises(AppError) as excinfo:
        validate_manual_path(str(outside), [allowed])
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_manual_path_symlink_escape_rejected(tmp_path) -> None:
    allowed = tmp_path / "sources"
    allowed.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(make_png_bytes())
    link = allowed / "link.png"
    link.symlink_to(outside)

    with pytest.raises(AppError) as excinfo:
        validate_manual_path(str(link), [allowed])
    assert excinfo.value.code is ErrorCode.UNSAFE_PATH


def test_manual_path_happy_path(tmp_path) -> None:
    allowed = tmp_path / "sources"
    allowed.mkdir()
    good = allowed / "shoe.png"
    good.write_bytes(make_png_bytes())
    assert validate_manual_path(str(good), [allowed]).name == "shoe.png"


def test_text_file_named_png_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_image_bytes(b"<html>not an image</html>")
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_IMAGE


def test_svg_masquerade_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_image_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>' + b"0" * 500_000)
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_IMAGE


def test_tiny_image_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_image_bytes(make_png_bytes(100, 100))
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_IMAGE


def test_oversize_bytes_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_image_bytes(b"x" * (MAX_IMAGE_BYTES + 1))
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_IMAGE


def test_valid_image_passes() -> None:
    meta = validate_image_bytes(make_png_bytes(1200, 800))
    assert meta["width"] == 1200
    assert meta["format"] == "PNG"
