"""上传图体检接口（POST /api/v1/inspect）的集成测试。

覆盖三档判定与"省钱"设计：
- 不带裁切框 → 只跑 CV（不调用视觉模型）；
- 带裁切框 → 调一次视觉模型，返回品牌/型号/Logo/文字；
- 明确不是鞋 → 友好拒绝（文案里要说出"我看到的更像什么"，且用「您」）；
- 不确定 → 放行 + 软提示；
- 体检次数护栏 → 超过 daily 上限返回额度类错误。
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.schemas.inspect import LogoInfo, PhotoInspectOut, ShoeText


def _png_base64(width: int = 1200, height: int = 1600, *, draw_shoe: bool = True) -> str:
    image = Image.new("RGB", (width, height), "white")
    if draw_shoe:
        draw = ImageDraw.Draw(image)
        draw.ellipse((200, 500, 900, 850), fill="#3344cc")  # 宽高比 2:1，像鞋
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _inspect(api: TestClient, *, crop: dict | None = None, image: str | None = None):
    body: dict = {"image_base64": image or _png_base64()}
    if crop:
        body["crop"] = crop
    return api.post("/api/v1/inspect", json=body)


def test_without_crop_only_runs_cv(api: TestClient) -> None:
    """不带裁切框：只做 CV 定位，返回建议框，且不应产生任何视觉模型调用（省钱）。"""
    response = _inspect(api)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["tier"] == "ok"
    assert data["ok"] is True
    assert data["crop"] is not None, "应返回建议裁切框供前端预填"
    assert data["image"] == {"width": 1200, "height": 1600}
    # 没有裁切框 = 用户还没确认 = 不做 AI 体检
    assert data["detail"]["display_name"] == ""
    assert data["detail"]["logo_type"] == ""


def test_multi_subject_without_crop_asks_user_to_crop(api: TestClient) -> None:
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    for x in (80, 640):
        for y in (300, 900):
            draw.ellipse((x, y, x + 400, y + 200), fill="#223399")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()

    data = _inspect(api, image=payload).json()
    assert data["tier"] == "multi"
    assert data["ok"] is False
    assert "好几双鞋" in data["message"]
    assert "您" in data["message"] and "你" not in data["message"]
    assert data["subject"]["count"] >= 4


def test_with_crop_returns_shoe_details(api: TestClient) -> None:
    """带裁切框：调用一次视觉模型（mock），拿到品牌/型号/Logo/文字。"""
    data = _inspect(api, crop={"x": 150, "y": 450, "w": 800, "h": 450}).json()

    assert data["ok"] is True
    assert data["tier"] == "ok"
    assert data["detail"]["display_name"] == "ASICS GEL-Nimbus 27"
    assert data["detail"]["logo_type"] == "两侧交叉条纹"
    assert data["detail"]["texts"] == ["GEL"]
    assert "认出来了" in data["message"]
    assert "您" in data["hint"]


def test_not_shoe_is_rejected_with_friendly_copy(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """明确不是鞋 → 拒绝，且文案要说出"我看到的更像什么"，并用「您」。"""

    def fake_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        return PhotoInspectOut(
            is_shoe=False,
            confidence=0.96,
            shoe_count=0,
            subject_description="马克杯",
        )

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", fake_inspect)

    data = _inspect(api, crop={"x": 150, "y": 450, "w": 800, "h": 450}).json()
    assert data["tier"] == "not_shoe"
    assert data["ok"] is False
    assert "马克杯" in data["message"]
    assert "不是运动鞋" in data["message"]
    assert "您" in data["hint"] and "你" not in data["hint"]


def test_uncertain_is_allowed_with_soft_hint(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """不确定 → 放行 + 软提示（拒绝太严比选错更伤体验）。"""

    def fake_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        return PhotoInspectOut(is_shoe=True, confidence=0.2, shoe_count=1)

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", fake_inspect)

    data = _inspect(api, crop={"x": 150, "y": 450, "w": 800, "h": 450}).json()
    assert data["tier"] == "uncertain"
    assert data["ok"] is True, "不确定也要放行"
    assert "不太确定" in data["message"]


def test_crop_must_be_sane(api: TestClient) -> None:
    response = _inspect(api, crop={"x": 0, "y": 0, "w": 0, "h": 10})
    assert response.status_code == 422  # pydantic 校验：w 必须 > 0


def test_bad_base64_is_rejected(api: TestClient) -> None:
    response = api.post("/api/v1/inspect", json={"image_base64": "!!!not-an-image!!!" * 4})
    assert response.status_code in (400, 422), response.text
    assert "INVALID_INPUT" in response.text or "校验" in response.text


def test_daily_inspect_guard(settings, tmp_path) -> None:
    """体检次数护栏：超过上限时报额度错误（避免手滑刷成本）。"""
    from fastapi.testclient import TestClient as _TC

    from app.core.config import Settings
    from app.main import create_app

    limited = Settings(
        _env_file=None,
        env="prod",  # 只有启用登录时才计数（与额度门一致）
        data_dir=str(tmp_path / "data"),
        force_mock_provider=True,
        enable_mock_provider=True,
        max_inspect_per_day=2,
        session_secret="test-secret",
        admin_code="TEST-ADMIN",
        storage_provider="local",
    )
    app = create_app(limited)
    # prod 下会话 Cookie 带 Secure 标记 → 测试必须用 https，否则 Cookie 不会被带上
    with _TC(app, base_url="https://testserver") as client:
        login = client.post("/api/v1/auth/login", json={"code": "TEST-ADMIN"})
        assert login.status_code == 200, login.text
        body = {"image_base64": _png_base64(), "crop": {"x": 150, "y": 450, "w": 800, "h": 450}}

        assert client.post("/api/v1/inspect", json=body).status_code == 200
        assert client.post("/api/v1/inspect", json=body).status_code == 200
        blocked = client.post("/api/v1/inspect", json=body)
        assert blocked.status_code == 429, blocked.text
        assert "QUOTA_EXCEEDED" in json.dumps(blocked.json(), ensure_ascii=False)
