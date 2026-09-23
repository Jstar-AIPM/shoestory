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


def test_upload_large_image_crops_client_region(api: TestClient) -> None:
    """超大图（服务端会缩）上传后，裁的必须是客户端框住的那一块。

    与 ``test_inspect_api`` 里同名思路的测试对称：那里盖体检，这里盖建任务。
    断言方式是“看画布颜色”—— 框对 → 画布是红的；坐标没换算 → 画布几乎全白。
    """
    from app.services.workflow.runner import SOURCE_FILENAME

    width, height = 3000, 2000  # 长边超 max_upload_edge(2400) → 触发缩图（系数 0.8）
    image = Image.new("RGB", (width, height), "white")
    # 小块（宽高比 2:1，像鞋）+ 紧贴的裁切框：坐标若不换算，框会整体向右下偏 25%，正好完全错过红块
    ImageDraw.Draw(image).rectangle((1000, 600, 1200, 700), fill=(220, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    payload = base64.b64encode(buffer.getvalue()).decode()

    task = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": payload,
            "crop": {"x": 980, "y": 580, "w": 240, "h": 140},
            "inspect": {"display_name": "ASICS GEL-Nimbus 27", "brand": "ASICS", "model_name": "GEL-Nimbus 27"},
        },
    ).json()
    assert task["state"] == "awaiting_effect_confirm", task

    container = api.app.state.container
    key = container.asset_store.task_key(container.settings.dev_owner_id, task["task_id"], SOURCE_FILENAME)
    canvas = np.array(Image.open(io.BytesIO(container.asset_store.get(key))).convert("RGB"))
    mean = canvas.reshape(-1, 3).mean(axis=0)
    assert float(mean[0]) - float(mean[1]) > 80, f"画布应以红块为主（说明裁对了区域），实际均值 {mean}"


def test_upload_exif_rotated_photo_crops_browser_region(api: TestClient) -> None:
    """EXIF 方向的手机照片：裁的必须是**浏览器里看到的那一块**。

    存储 1200×800 + EXIF 6 → 浏览器看到 800×1200（红块在 500,100-700,500）。
    服务端若不摆正，同一个框会裁到白底 —— 画出来的鞋就错了。
    这里直接查上传后存下的源图（source_0.png = 用户框住的那块），不经过生成链路。
    """
    from app.services.workflow.runner import SOURCE_FILENAME

    image = Image.new("RGB", (1200, 800), "white")
    ImageDraw.Draw(image).rectangle((100, 100, 500, 300), fill=(220, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    payload = base64.b64encode(buffer.getvalue()).decode()

    crop = {"x": 480, "y": 80, "w": 260, "h": 440}  # 摆正后的坐标系
    task = api.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": payload,
            "crop": crop,
            "inspect": {"display_name": "ASICS GEL-Nimbus 27", "brand": "ASICS", "model_name": "GEL-Nimbus 27"},
        },
    ).json()
    assert task["state"] == "awaiting_effect_confirm", task

    container = api.app.state.container
    key = container.asset_store.task_key(container.settings.dev_owner_id, task["task_id"], SOURCE_FILENAME)
    source = np.array(Image.open(io.BytesIO(container.asset_store.get(key))).convert("RGB"))
    assert source.shape[:2] == (crop["h"], crop["w"]), "源图应就是用户框住的那一块"
    center = source[crop["h"] // 2, crop["w"] // 2]
    corner = source[3, 3]
    assert int(center[0]) - int(center[1]) > 100, f"中心应是红块（说明摆正+裁对了），实际 {center}"
    assert corner.min() > 200, f"边角应是白底，实际 {corner}"


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


def _upload_with_inspect(api: TestClient, inspect: dict) -> dict:
    image = _shoe_png_base64()
    crop = {"x": 150, "y": 450, "w": 800, "h": 450}
    return api.post(
        "/api/v1/tasks/upload",
        json={"image_base64": image, "crop": crop, "inspect": inspect},
    ).json()


def _spy_generator(api: TestClient, monkeypatch) -> dict:
    """抓住传给生图模型的参数（用来断言"要不要要求/禁止画 Logo"）。"""
    generator = api.app.state.container.providers.generator
    original = generator.generate
    seen: dict = {}

    def spy(**kwargs):  # noqa: ANN001
        seen.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(generator, "generate", spy)
    return seen


def test_upload_with_visible_logo_asks_for_solid_fill(api: TestClient, monkeypatch) -> None:
    seen = _spy_generator(api, monkeypatch)
    _upload_with_inspect(
        api,
        {
            "display_name": "Nike Air Force 1",
            "brand": "Nike",
            "model_name": "Air Force 1",
            "logo_type": "耐克勾形",
            "logo_position": "鞋身两侧",
            "logo_fill_required": True,
            "texts": ["AIR"],
        },
    )
    assert seen["avoid_logo"] is False
    assert "耐克勾形" in (seen["logo_fill"] or "")
    assert seen["shoe_texts"] == ["AIR"]


def test_upload_without_visible_logo_forbids_inventing_one(api: TestClient, monkeypatch) -> None:
    """回归（线上 AJ36 实测）：原图那个角度看不到品牌标识时，必须明确禁止编造 Logo。

    以前照样要求"把 Logo 填实"，模型于是编了个装饰符号，质检判它错 → 整单失败、白烧两次生成。
    """
    seen = _spy_generator(api, monkeypatch)
    _upload_with_inspect(
        api,
        {
            "display_name": "Jordan Air Jordan 36",
            "brand": "Jordan",
            "model_name": "Air Jordan 36",
            "logo_type": "",  # 体检没看到品牌标识
            "texts": [],
        },
    )
    assert seen["avoid_logo"] is True
    assert not seen["logo_fill"]
