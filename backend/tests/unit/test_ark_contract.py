"""上游接口契约测试：把官方文档核对过的字段锁死，避免“真跑才发现字段不对”。

对应文档：
- 图片生成 API（Seedream 4.0-5.0）：参考图字段是 `image`（string / string[]），取值为 URL 或 data URI
- 图片理解（Chat API）：`{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`
"""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.cv.binarize import check_artwork, refine_lineart
from app.services.providers.ark_common import ArkClient


def png_bytes(width: int = 64, height: int = 64, color: int = 255) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (color, color, color)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self.status_code = 200
        self._payload = payload
        self.content = payload if isinstance(payload, bytes) else b""

    def json(self) -> dict:
        return self._payload  # type: ignore[return-value]

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """记录最后一次请求体，并按 URL 返回不同的假响应。"""

    last: dict = {}
    image_bytes = png_bytes(1024, 1024, 200)

    def __init__(self, **kwargs) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def request(self, method: str, url: str, headers=None, json=None) -> _FakeResponse:  # noqa: A002
        _FakeClient.last = {"method": method, "url": url, "json": json, "headers": headers or {}}
        if "images/generations" in url:
            return _FakeResponse(
                {"data": [{"b64_json": base64.b64encode(_FakeClient.image_bytes).decode()}]}
            )
        return _FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    def get(self, url: str) -> _FakeResponse:  # pragma: no cover - 兜底
        return _FakeResponse(b"")


@pytest.fixture
def ark(monkeypatch) -> ArkClient:
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return ArkClient(
        Settings(
            _env_file=None,
            ark_api_key="test-key",
            ark_text_model="doubao-seed-2-1-pro-260915",
            ark_vision_model="doubao-seed-2-1-pro-260915",
            ark_image_model="doubao-seedream-5-0-pro-260628",
        )
    )


def test_single_reference_image_uses_string_field(ark: ArkClient) -> None:
    ark.generate_image(model="m", prompt="p", size="1536x1024", image=png_bytes())
    payload = _FakeClient.last["json"]
    assert isinstance(payload["image"], str)
    assert payload["image"].startswith("data:image/png;base64,")
    assert "images" not in payload  # 官方字段名只有 image
    assert payload["size"] == "1536x1024"
    assert payload["response_format"] == "b64_json"


def test_multi_reference_images_use_array_field(ark: ArkClient) -> None:
    ark.generate_image(
        model="m", prompt="p", size="1536x1024", reference_images=[png_bytes(), png_bytes(), png_bytes()]
    )
    payload = _FakeClient.last["json"]
    assert isinstance(payload["image"], list)
    assert len(payload["image"]) == 3
    assert all(item.startswith("data:image/") for item in payload["image"])
    assert "images" not in payload


def test_size_tier_is_passed_through(ark: ArkClient) -> None:
    """Seedream 5.0 pro 支持分辨率档位（1K/1.5K/2K）；模板里怎么配就怎么传。"""
    ark.generate_image(model="m", prompt="p", size="2K", image=png_bytes())
    assert _FakeClient.last["json"]["size"] == "2K"


def test_chat_vision_uses_image_url_data_uri(ark: ArkClient) -> None:
    ark.chat_text(model="m", system="s", user="u", images=[("图1 原鞋", png_bytes(32, 32))])
    payload = _FakeClient.last["json"]
    content = payload["messages"][1]["content"]
    assert content[0]["type"] == "text"
    images = [item for item in content if item["type"] == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    # 图前带一段文字标签，帮助模型区分“原鞋参考图 / 待检线稿”
    labels = [item["text"] for item in content if item["type"] == "text"]
    assert any("原鞋" in label for label in labels)
    assert payload["temperature"] == 0.1


def test_auth_header_and_base_url(ark: ArkClient) -> None:
    ark.chat_text(model="m", system="s", user="u")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer test-key"
    assert _FakeClient.last["url"].startswith("https://ark.cn-beijing.volces.com/api/v3")


def test_missing_ark_key_maps_to_auth_error(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    class _Unauthorized(_FakeClient):
        def request(self, method, url, headers=None, json=None):  # noqa: A002
            response = _FakeResponse({"error": {"message": "no key"}})
            response.status_code = 401
            return response

    monkeypatch.setattr(httpx, "Client", _Unauthorized)
    client = ArkClient(Settings(_env_file=None, ark_api_key="bad"))
    with pytest.raises(AppError) as excinfo:
        client.generate_image(model="m", prompt="p", size="1536x1024")
    assert excinfo.value.code is ErrorCode.UPSTREAM_AUTH_FAILED
    assert "bad" not in excinfo.value.message  # 错误里不能出现密钥


def test_wrong_size_output_is_normalized_into_canvas() -> None:
    """上游返回任意尺寸（例如 1024x1024）时，后处理必须归一到 1536x1024 硬指标。"""
    square = png_bytes(1024, 1024)
    refined, meta = refine_lineart(square, target_width=1536, target_height=1024)
    check = check_artwork(refined, 1536, 1024)
    assert check["ratio_ok"] is True
    assert check["binary"] is True
    assert check["background_ok"] is True
    assert meta["normalized_to_canvas"] is True
    assert meta["output_size"] == "1536x1024"


def test_tall_output_is_letterboxed_not_cropped() -> None:
    """竖图不能被裁掉内容：应等比缩小 + 左右补白。"""
    tall = Image.new("L", (600, 1600), 255)
    for y in range(200, 1400):
        for x in range(250, 350):
            tall.putpixel((x, y), 0)
    buffer = io.BytesIO()
    tall.save(buffer, format="PNG")

    refined, _meta = refine_lineart(buffer.getvalue(), target_width=1536, target_height=1024)
    check = check_artwork(refined, 1536, 1024)
    assert check["canvas_score"] == 1.0
    # 墨水仍存在（没有被裁没）
    assert check["white_ratio"] < 0.99


def test_quality_report_json_roundtrip_still_valid() -> None:
    from app.schemas.llm import QualityReportOut

    report = QualityReportOut(
        shoe_silhouette_match=0.9,
        logo_legibility=0.85,
        style_consistency=0.9,
        noise_level=0.88,
    )
    assert json.loads(report.model_dump_json())["logo_legibility"] == 0.85
