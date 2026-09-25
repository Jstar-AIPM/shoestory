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


def test_large_image_keeps_client_coordinate_space(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """服务端缩过大图后，裁切框坐标必须仍在**客户端那张图**的坐标系里。

    真实风险：手机/截图原图可能远超 max_upload_edge。服务端一缩图，坐标空间就变了 ——
    若不换算，会静默地裁到鞋以外（不报错、只是画错鞋）。这里同时验证两件事：
    ① 响应里的 crop / image 尺寸回到原图坐标系；② 视觉模型收到的确实是客户端框的那一块。
    """
    import numpy as np

    width, height = 3000, 2000  # 长边 3000 > max_upload_edge(2400) → 触发缩图（系数 0.8）
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).rectangle((1000, 600, 1600, 900), fill=(220, 30, 30))  # 红块居中
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()

    seen: dict = {}

    def capturing_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        seen["arr"] = np.array(Image.open(io.BytesIO(image)).convert("RGB"))
        return PhotoInspectOut(
            is_shoe=True,
            confidence=0.95,
            shoe_count=1,
            brand="ASICS",
            model_name="GEL-Nimbus 27",
            logo=LogoInfo(type="两侧交叉条纹", position="鞋身两侧"),
            texts=[ShoeText(text="GEL", position="鞋侧中足")],
        )

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", capturing_inspect)

    crop = {"x": 900, "y": 500, "w": 800, "h": 400}  # 红块在框内居中
    data = _inspect(api, image=payload, crop=crop).json()
    assert data["tier"] == "ok", data
    assert data["crop"] == crop, "响应必须回到客户端原始坐标系（原图 3000x2000）"
    assert data["image"] == {"width": 3000, "height": 2000}

    arr = seen["arr"]
    out_h, out_w = arr.shape[:2]
    assert (out_w, out_h) == (640, 320), f"视觉模型拿到的应是换算后的裁切区，实际 {(out_w, out_h)}"
    center = arr[out_h // 2, out_w // 2]
    corner = arr[2, 2]
    assert center[0] > 180 and center[1] < 80, f"中心应是用户框里的红块，实际 {center}"
    assert corner.min() > 200, f"边角应是白底，说明没有裁错位置，实际 {corner}"


def _exif_shoe_base64() -> str:
    """带 EXIF 方向（6 = 需顺时针 90° 才正）的 JPEG：存储 1200×800，浏览器看到 800×1200。"""
    image = Image.new("RGB", (1200, 800), "white")
    ImageDraw.Draw(image).rectangle((100, 100, 500, 300), fill=(220, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return base64.b64encode(buffer.getvalue()).decode()


def test_exif_rotated_photo_uses_browser_coordinate_space(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """手机照片常见 EXIF 方向：浏览器会摆正显示，服务端也必须摆正，否则坐标系差 90°。

    客户端框的是**摆正后**的 800×1200 坐标系；服务端若不应用 EXIF，会拿这个框去裁未旋转的
    1200×800 图 —— 裁到的地方完全不同（静默错误）。这里直接看视觉模型收到的到底是哪一块。
    """
    import numpy as np

    seen: dict = {}

    def capturing_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        seen["arr"] = np.array(Image.open(io.BytesIO(image)).convert("RGB"))
        return PhotoInspectOut(
            is_shoe=True,
            confidence=0.95,
            shoe_count=1,
            brand="ASICS",
            model_name="GEL-Nimbus 27",
            logo=LogoInfo(type="两侧交叉条纹", position="鞋身两侧"),
            texts=[ShoeText(text="GEL", position="鞋侧中足")],
        )

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", capturing_inspect)

    # 摆正后红块在 (500,100)-(700,500)，框略大一圈
    crop = {"x": 480, "y": 80, "w": 260, "h": 440}
    data = _inspect(api, image=_exif_shoe_base64(), crop=crop).json()
    assert data["tier"] == "ok", data
    assert data["image"] == {"width": 800, "height": 1200}, "尺寸应是浏览器看到的（摆正后）"
    assert data["crop"] == crop, "响应坐标应在客户端（摆正后）坐标系里"

    arr = seen["arr"]
    out_h, out_w = arr.shape[:2]
    assert (out_w, out_h) == (260, 440)
    center = arr[out_h // 2, out_w // 2]
    corner = arr[2, 2]
    assert center[0] > 180 and center[1] < 80, f"中心应是红块（说明裁对了位置），实际 {center}"
    assert corner.min() > 200, f"边角应是白底，实际 {corner}"


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


def test_multi_crop_is_overridden_by_vision_when_it_sees_one_shoe(api: TestClient, monkeypatch) -> None:
    """回归（线上 AF1/AJ36 实测）：CV 在用户框好的区域里看到"第二个候选"时，先问视觉模型。

    商品页截图里同一双鞋会重复出现，加上饰片/文字块/∞ 标记，CV 很容易少数服从多数地判 multi；
    用户已经确认过框了，此时视觉模型认出"只有一双鞋"就应该放行（最多给一句软提示）。
    """
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    # 框里放两个"像鞋"的深色块：CV 必然判 multi（宽高比 2:1 的两个候选）
    draw.ellipse((100, 300, 500, 500), fill="#223399")
    draw.ellipse((100, 700, 500, 900), fill="#223399")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()

    def fake_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        return PhotoInspectOut(is_shoe=True, confidence=0.95, shoe_count=1, brand="Nike", model_name="Air Force 1")

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", fake_inspect)

    data = _inspect(api, image=payload, crop={"x": 80, "y": 280, "w": 440, "h": 640}).json()
    assert data["tier"] == "ok", data
    assert data["detail"]["display_name"] == "Nike Air Force 1"
    assert data["subject"]["count"] == 1


def test_multi_crop_still_asks_to_recrop_when_vision_sees_two(api: TestClient, monkeypatch) -> None:
    """视觉模型也认为框里不止一双时，仍然要提示重新框选（不能一律放行）。"""
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 300, 500, 500), fill="#223399")
    draw.ellipse((100, 700, 500, 900), fill="#223399")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()

    def fake_inspect(self, *, image: bytes, recorder) -> PhotoInspectOut:  # noqa: ANN001
        return PhotoInspectOut(is_shoe=True, confidence=0.9, shoe_count=2, brand="Nike", model_name="Air Force 1")

    monkeypatch.setattr("app.services.providers.mock.MockQualityJudge.inspect_photo", fake_inspect)

    data = _inspect(api, image=payload, crop={"x": 80, "y": 280, "w": 440, "h": 640}).json()
    assert data["tier"] == "multi"
    assert "不止一双" in data["message"]


def test_blur_warning_is_attached_on_every_ok_path(api) -> None:
    """清晰度提示必须挂到**每一条"可以画"的返回路径**上。

    2026-09-25 线上实测踩到：体检里"可以画"不止一条出路，还有一条是
    "CV 说框里多只鞋、但视觉模型说只有一只 → 放行"。第一版只加在最后一条上，
    结果线上怎么测都不提示。
    """
    png = _blurry_shoe_png()
    image = "data:image/png;base64," + __import__("base64").b64encode(png).decode()

    # 不带框：先拿建议框
    first = api.post("/api/v1/inspect", json={"image_base64": image}).json()
    crop = first.get("crop")
    assert crop, first

    # 带框：只要结论是"可以画"，就必须带提示
    second = api.post("/api/v1/inspect", json={"image_base64": image, "crop": crop}).json()
    if second["ok"]:
        assert second["warning"], f"可以画却没给清晰度提示：{second['tier']}"


def _blurry_shoe_png() -> bytes:
    """一张"鞋形 + 明显模糊"的图。"""
    import io

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 600), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.polygon([(120, 480), (330, 250), (700, 230), (800, 470)], fill=(70, 70, 70))
    arr = cv2.GaussianBlur(np.array(img), (31, 31), 0)
    buffer = io.BytesIO()
    Image.fromarray(arr).save(buffer, format="PNG")
    return buffer.getvalue()
