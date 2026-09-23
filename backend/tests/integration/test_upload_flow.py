"""上传图生成（V2 输入方式）的全链路集成测试：体检 → 上传建任务 → 生成 → 归档。

与 ``test_inspect_api.py`` 的分工：这里验证「体检结果接到生成」的闭环——
上传任务不调用视觉模型二次体检，而是复用 ``POST /inspect`` 已拿到的结论，
把裁切图当源图，把 Logo/文字注入生图提示词，把品牌+型号当归档标题。
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.services.cv.imageio import encode_png
from tests.conftest import archive_task


def _shoe_png_base64(width: int = 1200, height: int = 1600) -> str:
    """白底 + 一个「像鞋」的蓝色椭圆（宽高比约 2:1）。"""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 500, 900, 850), fill="#3344cc")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _inspect_with_crop(api: TestClient, image: str, crop: dict) -> dict:
    return api.post("/api/v1/inspect", json={"image_base64": image, "crop": crop}).json()


def test_upload_chain_uses_inspect_hints_and_archive_name(api: TestClient) -> None:
    image = _shoe_png_base64()
    crop = {"x": 150, "y": 450, "w": 800, "h": 450}

    # ① 体检（带裁切框，mock 视觉模型返回 ASICS + 交叉条纹 + GEL）
    inspected = _inspect_with_crop(api, image, crop)
    assert inspected["ok"] is True
    detail = inspected["detail"]
    assert detail["display_name"] == "ASICS GEL-Nimbus 27"
    assert detail["logo_type"] == "两侧交叉条纹"
    assert detail["texts"] == ["GEL"]

    # ② 上传建任务：把体检结论原样带回，不再二次调用视觉模型
    response = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": crop,
            "inspect": {
                "display_name": detail["display_name"],
                "brand": detail["brand"],
                "model_name": detail["model_name"],
                "colorway": detail["colorway"],
                "logo_type": detail["logo_type"],
                "logo_position": detail["logo_position"],
                "logo_fill_required": detail["logo_fill_required"],
                "texts": detail["texts"],
                "shoe_count": detail["shoe_count"],
            },
        },
    )
    assert response.status_code == 201, response.text
    task = response.json()
    # pipeline_inline 下同步跑完：应直接到人工效果确认点
    assert task["state"] == "awaiting_effect_confirm", task
    assert task["quality"]["score"] >= 0.80
    # 归档标题来源：体检识别的「品牌 + 型号」
    assert task["query"] == "ASICS GEL-Nimbus 27"

    # ③ 归档：默认标题用体检识别名
    created = archive_task(api, task["task_id"])
    listing = api.get("/api/v1/archive").json()
    assert listing["items"][0]["model_name"] == "ASICS GEL-Nimbus 27"
    assert created["shoe_id"]


def test_upload_does_not_call_vision_again(api: TestClient, monkeypatch) -> None:
    """上传任务不应触发第二次视觉体检（省钱：体检已在 /inspect 做过）。"""
    image = _shoe_png_base64()
    crop = {"x": 150, "y": 450, "w": 800, "h": 450}

    inspected = _inspect_with_crop(api, image, crop)
    detail = inspected["detail"]

    calls: list[str] = []
    original = api.app.state.container.providers.judge.inspect_photo

    def counting_inspect(*, image, recorder):  # noqa: ANN001
        calls.append("inspect_photo")
        return original(image=image, recorder=recorder)

    monkeypatch.setattr(
        api.app.state.container.providers.judge, "inspect_photo", counting_inspect
    )

    response = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": crop,
            "inspect": {
                "display_name": detail["display_name"],
                "brand": detail["brand"],
                "model_name": detail["model_name"],
                "logo_type": detail["logo_type"],
                "logo_position": detail["logo_position"],
                "texts": detail["texts"],
            },
        },
    )
    assert response.status_code == 201, response.text
    assert calls == [], "上传建任务不应再次调用视觉体检"


def test_upload_task_exposes_cv_draft(api: TestClient) -> None:
    """上传图任务预处理后会生成 CV 草稿（边缘骨架图），并暴露给前端做动效。"""
    image = _shoe_png_base64()
    crop = {"x": 150, "y": 450, "w": 800, "h": 450}
    detail = _inspect_with_crop(api, image, crop)["detail"]

    task = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": crop,
            "inspect": {"display_name": detail["display_name"], "brand": detail["brand"], "model_name": detail["model_name"]},
        },
    ).json()

    assert task["draft_url"], "上传任务应有 CV 草稿地址"
    draft = api.get(task["draft_url"])
    assert draft.status_code == 200
    assert draft.headers["content-type"] == "image/png"


def test_text_fallback_composites_when_text_illegible(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """文字兜底贴合：质检返回 text_legible 过低时，把原图裁出的文字贴到线稿上。

    这里 monkeypatch 了「裁贴片」这一步（确定性给一块黑贴片），只验证接线：
    质检低分 → 读取贴片 → 贴合到最终画稿。CV 裁贴片的正确性由 test_text_stamp.py 覆盖。
    """
    container = api.app.state.container
    runner = container.runner

    # ① 让质检返回低 text_legible
    original_judge = container.providers.judge.judge

    def low_text_judge(**kwargs):  # noqa: ANN001
        result = original_judge(**kwargs)  # judge.judge 直接返回 QualityReportOut
        result.text_legible = 0.1
        return result

    monkeypatch.setattr(container.providers.judge, "judge", low_text_judge)

    # ② 让「裁贴片」确定性产出一块 30x20 的全黑贴片（放在画布左上角）
    def fake_build(record, source_bytes, canvas, normalize_meta):  # noqa: ANN001
        stamp = np.zeros((20, 30), np.uint8)
        png = encode_png(Image.fromarray(stamp, mode="L"))
        runner.asset_store.put_task_file(record.owner_id, record.task_id, "text_stamp_0.png", png)
        return [{"box": [0, 0, 30, 20], "path": "text_stamp_0.png"}]

    monkeypatch.setattr(runner, "_build_text_stamps", fake_build)

    # ③ 上传建任务（pipeline_inline 同步跑完）
    image = _shoe_png_base64()
    crop = {"x": 150, "y": 450, "w": 800, "h": 450}
    detail = _inspect_with_crop(api, image, crop)["detail"]
    task = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": crop,
            "inspect": {
                "display_name": detail["display_name"],
                "brand": detail["brand"],
                "model_name": detail["model_name"],
                "texts": detail["texts"],
                "text_stamps": detail["text_stamps"],
            },
        },
    ).json()
    assert task["state"] == "awaiting_effect_confirm", task

    # ④ 画稿左上角应被贴入黑块（贴片已应用）
    artwork = api.get(task["artworks"][0]["url"])
    assert artwork.status_code == 200
    arr = np.array(Image.open(io.BytesIO(artwork.content)).convert("L"))
    assert (arr[5:15, 5:25] == 0).all(), "贴片应被贴合到画稿左上角"


def test_upload_bad_crop_is_rejected(api: TestClient) -> None:
    image = _shoe_png_base64()
    # 裁切范围太小（<32px）→ INVALID_INPUT
    response = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": {"x": 0, "y": 0, "w": 10, "h": 10},
            "inspect": {"display_name": "X"},
        },
    )
    assert response.status_code in (400, 422), response.text
    assert "INVALID_INPUT" in response.text or "校验" in response.text


def test_upload_requires_sane_crop_schema(api: TestClient) -> None:
    image = _shoe_png_base64()
    response = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": image,
            "crop": {"x": 0, "y": 0, "w": 0, "h": 10},
            "inspect": {"display_name": "X"},
        },
    )
    assert response.status_code == 422  # pydantic：w 必须 > 0


def test_upload_bad_base64_rejected(api: TestClient) -> None:
    response = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": "!!!not-an-image!!!" * 4,
            "crop": {"x": 0, "y": 0, "w": 100, "h": 100},
            "inspect": {},
        },
    )
    assert response.status_code in (400, 422), response.text
    assert "INVALID_INPUT" in response.text or "校验" in response.text
