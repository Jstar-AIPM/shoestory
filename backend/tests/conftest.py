"""测试夹具：每个测试用独立的临时 data 目录 + mock 上游，离线可跑。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.core.container import Container, build_container
from app.main import create_app


#: 集成测试统一用哪个风格。
#: 这些用例测的是**黑白线稿的机制**（纯二值画稿、Logo 填色提示、文字兜底等）。
#: 2026-09-24 起主风格切成水彩、黑白被设为 hidden（不对外提供，但**代码保留**、
#: 显式指定仍可用），所以测试显式指定它；水彩路径另有专门测试。
TEST_STYLE_ID = "bw_lineart"


def make_png_bytes(width: int = 1200, height: int = 800, color: tuple[int, int, int] = (60, 60, 60)) -> bytes:
    """造一张“像鞋图”的 PNG，用于手动源图与文件校验测试。"""
    img = Image.new("RGB", (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.polygon(
        [(100, height - 80), (200, height - 320), (width - 250, height - 500), (width - 80, height - 80)],
        fill=color,
        outline=(10, 10, 10),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    allowed = tmp_path / "sources"
    allowed.mkdir(parents=True, exist_ok=True)
    return Settings(
        _env_file=None,  # 不读仓库 .env，保证测试隔离与可复现
        env="dev",
        data_dir=str(tmp_path / "data"),
        dev_owner_id="owner",
        ark_api_key="",
        force_mock_provider=True,
        enable_mock_provider=True,
        pipeline_inline=True,
        mock_quality="good",
        allowed_source_dirs=str(allowed),
        app_log_level="WARNING",
        style_id=TEST_STYLE_ID,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> TestClient:
    return client


@pytest.fixture
def client_factory(tmp_path: Path):
    """按需定制配置的客户端工厂（例如 mock_quality="low"、task_max_upstream_calls=2）。"""

    def _make(**overrides):
        allowed = tmp_path / "sources"
        allowed.mkdir(parents=True, exist_ok=True)
        base: dict = {
            "_env_file": None,
            "env": "dev",
            "data_dir": str(tmp_path / "data"),
            "dev_owner_id": "owner",
            "ark_api_key": "",
            "force_mock_provider": True,
            "enable_mock_provider": True,
            "pipeline_inline": True,
            "mock_quality": "good",
            "allowed_source_dirs": str(allowed),
            "app_log_level": "WARNING",
            "style_id": TEST_STYLE_ID,
            # 阶段 4：默认关闭强制登录，便于既有用例；需要鉴权的用例显式传 env="prod"
        }
        base.update(overrides)
        settings = Settings(**base)
        # prod 模式下会话 Cookie 带 Secure（安全要求）→ 测试必须走 https 才会被回传
        scheme = "https" if settings.env == "prod" else "http"
        return TestClient(create_app(settings), base_url=f"{scheme}://testserver")

    return _make


class EmptySearchProvider:
    """测试替身：模拟搜图上游“正常响应但没找到图”（业务结果，不是系统错误）。"""

    name = "stub-empty"
    mode = "mock"

    def search(self, *, model_name: str, limit: int, recorder) -> list:
        recorder.check("search")
        recorder.record("search", provider=self.name, detail={"found": 0})
        return []


def create_task(client: TestClient, query: str = "kd12") -> dict:
    response = client.post("/api/v1/tasks", json={"query": query})
    assert response.status_code == 201, response.text
    return response.json()


def run_to_artwork(client: TestClient, query: str = "kd12", index: int = 0) -> dict:
    """走到 awaiting_effect_confirm（或 failed），返回最终任务对象。"""
    task = create_task(client, query)
    assert task["state"] == "awaiting_source_confirm", task
    response = client.post(f"/api/v1/tasks/{task['task_id']}/source", json={"selected_index": index})
    assert response.status_code == 202, response.text
    return client.get(f"/api/v1/tasks/{task['task_id']}").json()


def archive_task(client: TestClient, task_id: str, **payload) -> dict:
    response = client.post(f"/api/v1/tasks/{task_id}/archive", json=payload)
    assert response.status_code == 201, response.text
    return response.json()
