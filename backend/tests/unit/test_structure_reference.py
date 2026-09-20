"""结构骨架参考（防自由创作）+ “每轮 1 张”的产品决定。"""

from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from app.core.config import STYLES_DIR, Settings
from app.services.cv.edges import extract_edge_map
from app.services.providers.ark_image import ArkLineartGenerator
from app.services.style.registry import StyleRegistry


def canvas_bytes(width: int = 1536, height: int = 1024) -> bytes:
    """造一张“有主体轮廓”的画布图（白底 + 深色鞋形块）。"""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.polygon(
        [
            (int(width * 0.12), int(height * 0.72)),
            (int(width * 0.30), int(height * 0.34)),
            (int(width * 0.74), int(height * 0.26)),
            (int(width * 0.88), int(height * 0.70)),
        ],
        fill=(40, 40, 60),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_edge_map_is_white_background_black_line() -> None:
    edges, meta = extract_edge_map(canvas_bytes())
    image = Image.open(io.BytesIO(edges)).convert("L")
    assert image.size[0] <= 1024
    pixel_values = set(image.getdata())
    assert pixel_values <= {0, 255}  # 只有黑白
    assert meta["ink_ratio"] > 0.0005  # 确实抽到了线条
    assert meta["ink_ratio"] < 0.5
    assert len(edges) < 400_000  # 作为参考图，体积可控


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
        _Capture.last = json or {}
        import base64

        buffer = io.BytesIO()
        Image.new("RGB", (1536, 1024), (255, 255, 255)).save(buffer, format="PNG")
        payload = {"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]}

        class _Response:
            status_code = 200

            def json(self_inner):
                return payload

        return _Response()


@pytest.fixture
def generator(monkeypatch) -> ArkLineartGenerator:
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return ArkLineartGenerator(
        Settings(_env_file=None, ark_api_key="k", ark_image_model="doubao-seedream-5-0-pro-260628")
    )


class _Recorder:
    def check(self, kind):  # noqa: D102
        return None

    def record(self, *args, **kwargs):  # noqa: D102
        return None


def test_structure_reference_is_sent_as_second_image(generator: ArkLineartGenerator) -> None:
    style = StyleRegistry(STYLES_DIR).get("bw_lineart")
    edges, _meta = extract_edge_map(canvas_bytes())

    generator.generate(
        canvas_png=canvas_bytes(),
        style=style,
        attempt=1,
        recorder=_Recorder(),
        structure_reference=edges,
    )

    payload = _Capture.last
    assert isinstance(payload["image"], list)  # 多参考图 = 数组
    assert len(payload["image"]) == 2
    assert all(item.startswith("data:image/") for item in payload["image"])
    assert "骨架" in payload["prompt"]  # 提示词里解释了第二张图的作用


def test_without_structure_reference_only_photo_is_sent(generator: ArkLineartGenerator) -> None:
    style = StyleRegistry(STYLES_DIR).get("bw_lineart")
    generator.generate(
        canvas_png=canvas_bytes(), style=style, attempt=1, recorder=_Recorder()
    )
    payload = _Capture.last
    assert isinstance(payload["image"], str)  # 单图 = 字符串
    assert "骨架" not in payload["prompt"]


def test_style_prompt_bans_hatching() -> None:
    style = StyleRegistry(STYLES_DIR).get("bw_lineart")
    assert "排线" in style.prompt.positive
    assert "排线" in style.prompt.negative
    assert "交叉影线" in style.prompt.negative


def test_default_internal_attempts_are_two() -> None:
    """用户只看到 1 张；内部最多画 2 张（第 1 张不合格时自动补画 1 张）。"""
    assert Settings(_env_file=None).gen_max_attempts == 2


def test_generation_speed_default_is_fast() -> None:
    """默认用 fast 模式（官方 optimize_prompt_options.mode）：实测 80 秒 -> 30 秒。"""
    assert Settings(_env_file=None).image_prompt_optimize_mode == "fast"
