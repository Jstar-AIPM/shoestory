"""给视觉质检的图片必须降采样（真实踩坑：直接送 4MB 原图会让质检超时）。"""

from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from app.core.config import Settings
from app.services.cv.imageio import prepare_for_vision
from app.services.providers.ark_common import ArkClient, data_uri
from app.services.providers.ark_vision import ArkQualityJudge
from app.services.style.registry import StyleRegistry
from app.core.config import STYLES_DIR


def png_bytes(width: int, height: int) -> bytes:
    """造一张“像照片”的图：渐变 + 噪点（PNG 很大，JPEG 会小很多，贴近真实场景）。"""
    import numpy as np

    rng = np.random.default_rng(7)
    base = np.linspace(60, 220, width, dtype=np.float32)[None, :]
    rows = np.linspace(40, 200, height, dtype=np.float32)[:, None]
    gray = np.clip(base * 0.6 + rows * 0.4 + rng.normal(0, 18, (height, width)), 0, 255)
    img = Image.fromarray(gray.astype("uint8"), mode="L").convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_for_vision_caps_long_edge_and_shrinks() -> None:
    big = png_bytes(1707, 1280)
    small = prepare_for_vision(big, max_edge=1024)
    assert len(small) < len(big)  # 照片类图片：JPEG 明显小于原 PNG
    image = Image.open(io.BytesIO(small))
    assert image.format == "JPEG"
    assert max(image.size) == 1024
    assert len(small) < 400_000  # 单张 base64 量级可控（原来可能 ~4MB）


def test_prepare_for_vision_keeps_small_images_untouched_in_size() -> None:
    tiny = png_bytes(400, 300)
    out = prepare_for_vision(tiny, max_edge=1024)
    assert Image.open(io.BytesIO(out)).size == (400, 300)


def test_prepare_for_vision_keeps_aspect_ratio() -> None:
    out = prepare_for_vision(png_bytes(1707, 1280), max_edge=1024)
    width, height = Image.open(io.BytesIO(out)).size
    assert abs(width / height - 1707 / 1280) < 0.02


def test_data_uri_detects_mime_from_magic_bytes() -> None:
    assert data_uri(png_bytes(20, 20)).startswith("data:image/png;base64,")
    jpeg = prepare_for_vision(png_bytes(40, 40))
    assert data_uri(jpeg).startswith("data:image/jpeg;base64,")


class _Capture:
    last: dict = {}


class _FakeClient:
    def __init__(self, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False

    def request(self, method, url, headers=None, json=None):  # noqa: A002
        _Capture.last = {"url": url, "json": json}

        class _Response:
            status_code = 200

            def json(self_inner):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"shoe_silhouette_match": 0.8, "logo_legibility": 0.8,'
                                    ' "style_consistency": 0.8, "noise_level": 0.8, "issues": []}'
                                )
                            }
                        }
                    ]
                }

        return _Response()


def test_judge_sends_downscaled_images_with_thinking_disabled(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    settings = Settings(
        _env_file=None,
        ark_api_key="k",
        ark_text_model="m",
        ark_vision_model="m",
        ark_image_model="m",
        ark_disable_thinking=True,
        ark_max_image_edge=1024,
    )
    judge = ArkQualityJudge(settings)
    style = StyleRegistry(STYLES_DIR).get("bw_lineart")

    class _Recorder:
        def check(self, kind):  # noqa: D102
            return None

        def record(self, *args, **kwargs):  # noqa: D102
            return None

    judge.judge(
        model_name="ASICS GEL-NIMBUS 27",
        style=style,
        source_png=png_bytes(1536, 1024),
        artwork_png=png_bytes(1536, 1024),
        recorder=_Recorder(),
    )

    payload = _Capture.last["json"]
    assert payload["thinking"] == {"type": "disabled"}  # 关掉深度思考 -> 更快更省开销
    content = payload["messages"][1]["content"]
    images = [item for item in content if item["type"] == "image_url"]
    assert len(images) == 2
    for item in images:
        uri = item["image_url"]["url"]
        assert uri.startswith("data:image/jpeg;base64,")
        raw = uri.split(",", 1)[1]
        assert len(raw) < 400_000  # 单张 base64 远小于原来的 ~4MB


def test_thinking_can_be_enabled_back(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    client = ArkClient(Settings(_env_file=None, ark_api_key="k", ark_disable_thinking=False))
    client.chat_text(model="m", system="s", user="u")
    assert "thinking" not in _Capture.last["json"]
