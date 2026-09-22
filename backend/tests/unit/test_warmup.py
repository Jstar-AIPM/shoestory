"""自预热（keep-warm）的行为测试。

线上实测：弹性实例空闲后，网关到实例的长连接先失效 → 「空闲后第一个请求」能卡 60–180s。
自预热线程按间隔请求自己的公网地址，把这条连接一直焐热（详见 services/warmup.py 的取舍说明）。
这里锁定三件事：默认不开、会按 URL 发请求、失败绝不抛出。
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.warmup import WarmupLoop


def test_disabled_without_urls() -> None:
    loop = WarmupLoop([])
    assert loop.enabled is False
    loop.start()  # 不应起线程
    assert loop._thread is None  # noqa: SLF001 - 明确断言“没起线程”


def test_settings_drive_warmup(monkeypatch) -> None:
    """配置默认关闭；ENABLE_WARMUP=true 且有 URL 时才生效。"""
    assert Settings(_env_file=None, enable_warmup=False).enable_warmup is False
    settings = Settings(
        _env_file=None,
        enable_warmup=True,
        warmup_urls="https://a.example.com/,https://b.example.com/api/v1/health",
    )
    urls = [u.strip() for u in settings.warmup_urls.split(",") if u.strip()]
    assert WarmupLoop(urls).enabled is True
    assert len(urls) == 2


def test_ping_once_hits_every_url(monkeypatch) -> None:
    called: list[str] = []

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        called.append(url)
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    loop = WarmupLoop(["https://a.example.com/", "https://b.example.com/health"])
    results = loop.ping_once()

    assert called == ["https://a.example.com/", "https://b.example.com/health"]
    assert all(ok for _url, ok, _status in results)
    assert [status for _u, _ok, status in results] == ["HTTP 200", "HTTP 200"]


def test_ping_once_never_raises(monkeypatch) -> None:
    def boom(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectTimeout("gateway connection stale")

    monkeypatch.setattr(httpx, "get", boom)
    loop = WarmupLoop(["https://a.example.com/"])
    results = loop.ping_once()  # 不应抛出

    assert results == [("https://a.example.com/", False, "ConnectTimeout")]


def test_interval_has_floor(monkeypatch) -> None:
    """间隔设成 1 秒会被抬到 30 秒，避免把调用量无意义地打满。"""
    assert WarmupLoop(["https://a.example.com/"], interval_seconds=1).interval == 30
    assert WarmupLoop(["https://a.example.com/"], interval_seconds=180).interval == 180


def test_5xx_counts_as_not_ok_but_4xx_is_fine(monkeypatch) -> None:
    """405（我们的定时触发器打根路径就是 405）属于“连接是通的”；5xx 才算预热失败。"""
    def status_response(code: int):
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(code, request=httpx.Request("GET", url))
        return fake_get

    monkeypatch.setattr(httpx, "get", status_response(405))
    assert WarmupLoop(["https://a.example.com/"]).ping_once()[0][1] is True

    monkeypatch.setattr(httpx, "get", status_response(503))
    assert WarmupLoop(["https://a.example.com/"]).ping_once()[0][1] is False
