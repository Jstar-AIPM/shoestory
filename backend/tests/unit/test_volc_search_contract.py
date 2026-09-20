"""豆包搜索 Custom 版（文搜图）契约测试：按官方文档字段锁死。

文档：docs.volcengine.com/docs/87772/2272953
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.services.providers.base import CallRecorder
from app.services.providers.volc_image_search import DEFAULT_ENDPOINT, VolcImageSearchProvider
from app.services.tools.rank_source_images import rank_source_images


class _Capture:
    last: dict = {}


def _client_factory(response_payload: dict, status_code: int = 200):
    class _Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self):
            return response_payload

    class _Client:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def post(self, url, headers=None, json=None):  # noqa: A002
            _Capture.last = {"url": url, "headers": headers or {}, "json": json}
            return _Response()

    return _Client


DOC_SAMPLE = {
    "ResponseMetadata": {"RequestId": "abc123"},
    "Result": {
        "ResultCount": 3,
        "ImageResults": [
            {
                "Id": "1",
                "SortId": 1,
                "Title": "Nike KD 12 侧视图",
                "SiteName": "example.com",
                "Url": "https://example.com/page1",
                "Image": {
                    "Url": "https://img.example.com/a.jpg",
                    "Width": 1600,
                    "Height": 1000,
                    "Shape": "横长方形",
                    "BlurDes": "清晰",
                    "Watermark": "0",
                },
                "RankScore": 0.91,
            },
            {
                "Id": "2",
                "SortId": 2,
                "Image": {
                    "Url": "https://img.example.com/b.jpg",
                    "Width": 800,
                    "Height": 800,
                    "Shape": "方形",
                    "BlurDes": "模糊",
                    "Watermark": "1",
                },
                "RankScore": 0.5,
            },
            {"Id": "3", "Image": {"Width": 900, "Height": 900}},  # 没有 Url -> 应被跳过
        ],
        "TimeCost": 168,
    },
}


def make_provider(monkeypatch, payload=DOC_SAMPLE, status_code: int = 200) -> VolcImageSearchProvider:
    monkeypatch.setattr(httpx, "Client", _client_factory(payload, status_code))
    settings = Settings(
        _env_file=None,
        volc_search_api_key="test-search-key",
        search_max_images=5,
        search_image_width_min=800,
    )
    return VolcImageSearchProvider(settings)


def make_recorder() -> CallRecorder:
    return CallRecorder(10, Settings(_env_file=None))


def test_request_matches_documented_contract(monkeypatch) -> None:
    provider = make_provider(monkeypatch)
    provider.search(model_name="Nike KD 12", limit=5, recorder=make_recorder())

    request = _Capture.last
    assert request["url"] == DEFAULT_ENDPOINT
    assert request["headers"]["Authorization"] == "Bearer test-search-key"
    body = request["json"]
    assert body["Query"] == "Nike KD 12"
    assert body["SearchType"] == "image"
    assert body["Count"] == 5
    assert body["Filter"]["ImageWidthMin"] == 800
    assert body["Filter"]["ImageShapes"] == ["横长方形"]
    assert body["QueryControl"]["QueryRewrite"] is False


def test_response_parsing_extracts_url_size_and_quality_flags(monkeypatch) -> None:
    provider = make_provider(monkeypatch)
    candidates = provider.search(model_name="Nike KD 12", limit=5, recorder=make_recorder())

    assert len(candidates) == 2  # 无 Url 的条目被跳过
    first = candidates[0]
    assert first.url == "https://img.example.com/a.jpg"
    assert (first.width, first.height) == (1600, 1000)
    assert first.blur == "清晰"
    assert str(first.watermark) == "0"
    assert first.shape == "横长方形"
    assert first.credit.startswith("图源来自公开检索")


def test_query_is_truncated_to_documented_limit(monkeypatch) -> None:
    provider = make_provider(monkeypatch)
    provider.search(model_name="x" * 200, limit=3, recorder=make_recorder())
    assert len(_Capture.last["json"]["Query"]) == 100


def test_count_is_capped_at_five(monkeypatch) -> None:
    provider = make_provider(monkeypatch)
    provider.search(model_name="kd12", limit=20, recorder=make_recorder())
    assert _Capture.last["json"]["Count"] == 5


def test_upstream_error_in_metadata_maps_to_auth_error(monkeypatch) -> None:
    payload = {"ResponseMetadata": {"Error": {"Code": "InvalidCredential", "Message": "bad key"}}}
    provider = make_provider(monkeypatch, payload)
    with pytest.raises(AppError) as excinfo:
        provider.search(model_name="kd12", limit=5, recorder=make_recorder())
    assert excinfo.value.code is ErrorCode.UPSTREAM_AUTH_FAILED


def test_http_401_maps_to_auth_error(monkeypatch) -> None:
    provider = make_provider(monkeypatch, {}, status_code=401)
    with pytest.raises(AppError) as excinfo:
        provider.search(model_name="kd12", limit=5, recorder=make_recorder())
    assert excinfo.value.code is ErrorCode.UPSTREAM_AUTH_FAILED


def test_empty_result_is_business_result_not_exception(monkeypatch) -> None:
    provider = make_provider(monkeypatch, {"ResponseMetadata": {}, "Result": None})
    assert provider.search(model_name="kd12", limit=5, recorder=make_recorder()) == []


def test_ranking_prefers_clear_watermark_free_landscape(monkeypatch) -> None:
    provider = make_provider(monkeypatch)
    ranked = rank_source_images(provider.search(model_name="kd12", limit=5, recorder=make_recorder()))
    assert ranked[0].url.endswith("a.jpg")  # 清晰 + 无水印 + 横长方形
    assert [c.index for c in ranked] == [0, 1]
