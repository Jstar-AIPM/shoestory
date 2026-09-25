"""全链路 API 测试（mock 上游）：创建 → 选源图 → 生成 → 质检 → 归档 → 鞋柜。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    EmptySearchProvider,
    archive_task,
    create_task,
    make_png_bytes,
    run_to_artwork,
)


def test_health_reports_missing_key_honestly(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["providers"]["ark"] == "missing_key"  # 没配 Key 就如实说，不假装
    assert body["providers"]["mode"] == "mock"
    assert body["flags"]["mock_mode"] is True


def test_styles_endpoint(client: TestClient) -> None:
    """风格列表只列**对外开放**的风格。

    2026-09-24：主风格切成水彩，黑白线稿设为 hidden（不对外提供），
    所以列表里只应有 watercolor —— 但黑白那份文件还在、也还能被显式指定（见下一个用例）。
    """
    styles = {s["style_id"]: s for s in client.get("/api/v1/styles").json()}
    assert "watercolor" in styles
    assert "bw_lineart" not in styles, "已隐藏的风格不该出现在对用户的列表里"
    assert all(s["canvas"]["aspect_ratio"] == "3:2" for s in styles.values())


def test_full_chain_archive_and_read_back(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    assert task["state"] == "awaiting_effect_confirm", task
    assert task["quality"]["score"] >= 0.80
    assert task["artworks"][0]["passed"] is True
    assert task["artworks"][0]["url"].endswith("/artworks/1.png")
    assert task["normalize"]["normalized"] == "Nike KD 12"

    artwork = client.get(task["artworks"][0]["url"])
    assert artwork.status_code == 200
    assert artwork.headers["content-type"] == "image/png"

    created = archive_task(
        client, task["task_id"], date_text="2021年6月", story="高三那年买的"
    )
    assert created["date_sort_key"] == "2021-06-01"

    listing = client.get("/api/v1/archive?sort=date").json()
    assert listing["total"] == 1
    assert listing["items"][0]["model_name"] == "Nike KD 12"
    assert listing["items"][0]["has_story"] is True

    detail = client.get(f"/api/v1/archive/{created['shoe_id']}").json()
    assert detail["story"] == "高三那年买的"
    assert detail["artwork_meta"]["width"] == 1536
    assert detail["artwork_meta"]["binary"] is True
    assert detail["rights_note"].startswith("个人纪念性再创作")

    archived_artwork = client.get(detail["artwork_url"])
    assert archived_artwork.status_code == 200
    assert archived_artwork.headers.get("ETag")

    # 任务已归档，再次归档应被状态机拒绝
    again = client.post(f"/api/v1/tasks/{task['task_id']}/archive", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE"


def test_archive_without_date_sorts_last(client: TestClient) -> None:
    first = run_to_artwork(client, "kd12")
    archive_task(client, first["task_id"], date_text="2019")

    second = run_to_artwork(client, "nike pg6")
    archive_task(client, second["task_id"], date_text="高三那年")

    items = client.get("/api/v1/archive").json()["items"]
    assert [item["date_text"] for item in items] == ["2019", "高三那年"]
    assert items[1]["date_sort_key"] is None


def test_model_not_found_is_business_result_with_candidates(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={"query": "nike kd 999"})
    assert response.status_code == 201  # 业务结果，不是系统错误
    task = response.json()
    assert task["state"] == "model_not_found"
    assert task["normalize"]["candidates"]
    assert task["source_candidates"] == []
    assert task["can"]["select_source"] is False


def test_image_search_empty_can_fall_back_to_manual_source(
    client: TestClient, settings, tmp_path
) -> None:
    # 用 stub 模拟“搜图返回空”——不往生产代码里塞测试标记
    client.app.state.container.providers.search = EmptySearchProvider()

    task = create_task(client, "kd12")
    assert task["state"] == "resolve_failed"
    response = client.get(f"/api/v1/tasks/{task['task_id']}")
    assert response.json()["error"]["code"] == "IMAGE_SEARCH_EMPTY"

    # 走“高级 · 手动给一张源图”兜底
    allowed = settings.allowed_source_dir_list[0]
    image_path = allowed / "manual.png"
    image_path.write_bytes(make_png_bytes())

    started = client.post(
        f"/api/v1/tasks/{task['task_id']}/source", json={"manual_path": str(image_path)}
    )
    assert started.status_code == 202, started.text
    final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
    assert final["state"] == "awaiting_effect_confirm"
    assert final["quality"]["score"] >= 0.80


def test_prod_requires_login_before_anything_else(client_factory) -> None:
    """prod 下未登录的请求一律 401（邀请码登录是访问前提）。"""
    with client_factory(env="prod") as prod_client:
        response = prod_client.post("/api/v1/tasks", json={"query": "kd12"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_manual_source_disabled_in_prod_when_logged_in(client_factory) -> None:
    """已登录的 prod 环境下，"手动指定源图"仍然关闭（V1 不做上传）。"""
    with client_factory(env="prod", enable_manual_source=False, admin_code="ADMINLOCAL") as prod_client:
        login = prod_client.post("/api/v1/auth/login", json={"code": "ADMINLOCAL"})
        assert login.status_code == 200, login.text

        prod_client.app.state.container.providers.search = EmptySearchProvider()
        response = prod_client.post("/api/v1/tasks", json={"query": "kd12"})
        assert response.status_code == 201, response.text
        task_id = response.json()["task_id"]

        blocked = prod_client.post(
            f"/api/v1/tasks/{task_id}/source", json={"manual_path": "./tmp/x.png"}
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "MANUAL_SOURCE_DISABLED"


def test_regenerate_keeps_previous_artworks(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    assert len(task["artworks"]) == 1

    response = client.post(
        f"/api/v1/tasks/{task['task_id']}/regenerate", json={"note": "线条有点乱"}
    )
    assert response.status_code == 202

    final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
    assert final["state"] == "awaiting_effect_confirm"
    assert len(final["artworks"]) == 2  # 上一次的画稿不消失
    assert final["attempts"] if "attempts" in final else True
    for art in final["artworks"]:
        assert client.get(art["url"]).status_code == 200


def test_regenerate_requires_effect_confirm_state(client: TestClient) -> None:
    task = create_task(client, "kd12")
    response = client.post(f"/api/v1/tasks/{task['task_id']}/regenerate", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"


def test_archive_allowed_after_failed_quality_takes_best(client_factory) -> None:
    """质检没过也要能归档（用户裁决）：不再 dead-end。"""
    with client_factory(mock_quality="low") as low_client:
        task = run_to_artwork(low_client, "kd12")
        assert task["state"] == "awaiting_effect_confirm"
        assert task["quality"]["verdict"] == "fail"
        # 默认内部最多 2 张：第 1 张不合格会自动补 1 张，仍不过则交用户裁决
        assert len(task["artworks"]) == 2
        assert task["quality"]["best_attempt"] is not None
        assert task["error"] is None
        # 用户裁决：“就这张，归档”
        created = archive_task(low_client, task["task_id"])
        assert created["shoe_id"]


def test_cancel_then_no_further_actions(client: TestClient) -> None:
    task = create_task(client, "kd12")
    assert client.post(f"/api/v1/tasks/{task['task_id']}/cancel").status_code == 200
    assert client.get(f"/api/v1/tasks/{task['task_id']}").json()["state"] == "cancelled"
    response = client.post(f"/api/v1/tasks/{task['task_id']}/source", json={"selected_index": 0})
    assert response.status_code == 409


def test_unknown_ids_return_404(client: TestClient) -> None:
    assert client.get("/api/v1/tasks/tk_missing").status_code == 404
    assert client.get("/api/v1/archive/sh_missing").status_code == 404
    detail = client.get("/api/v1/archive/sh_missing")
    assert detail.json()["error"]["code"] == "ARCHIVE_NOT_FOUND"


def test_artwork_attempt_not_found(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    response = client.get(f"/api/v1/tasks/{task['task_id']}/artworks/9.png")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTWORK_NOT_FOUND"


def test_unknown_style_rejected(client: TestClient) -> None:
    """请求里显式给了不存在的风格 → 报错，**不能悄悄换一个**。

    注意：别拿 watercolor 当"不存在的风格"（它 2026-09-24 起真的存在了），
    也别拿 bw_lineart（它存在、只是已隐藏 —— 隐藏≠禁用，显式指定仍然照办）。
    """
    response = client.post("/api/v1/tasks", json={"query": "kd12", "style_id": "no_such_style"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STYLE_NOT_FOUND"


def test_edit_archive_reparses_date(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    created = archive_task(client, task["task_id"], date_text="2019-2021")

    patched = client.patch(
        f"/api/v1/archive/{created['shoe_id']}",
        json={"story": "改过的故事", "date_text": "2021-06-15"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["date_sort_key"] == "2021-06-15"
    assert body["story"] == "改过的故事"

    blank = client.patch(f"/api/v1/archive/{created['shoe_id']}", json={"date_text": ""})
    assert blank.status_code == 200
    assert blank.json()["date_sort_key"] is None


def test_delete_requires_confirm_and_removes_files(client: TestClient, settings) -> None:
    task = run_to_artwork(client, "kd12")
    created = archive_task(client, task["task_id"])

    refused = client.delete(f"/api/v1/archive/{created['shoe_id']}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CONFIRM_REQUIRED"

    deleted = client.delete(f"/api/v1/archive/{created['shoe_id']}?confirm=true")
    assert deleted.status_code == 200
    assert deleted.json()["removed_files"] >= 1
    assert client.get("/api/v1/archive").json()["total"] == 0
    assert client.get(f"/api/v1/archive/{created['shoe_id']}").status_code == 404


def test_validation_errors_use_unified_shape(client: TestClient) -> None:
    cases = [
        ({"query": "   "}, 422),
        ({"query": "x" * 80}, 422),
        ({"query": "kd12", "unexpected": 1}, 422),
    ]
    for payload, expected in cases:
        response = client.post("/api/v1/tasks", json=payload)
        assert response.status_code == expected
        body = response.json()
        assert body["error"]["code"] == "INVALID_INPUT"
        assert body["error"]["message"]

    task = run_to_artwork(client, "kd12")
    too_long = client.post(
        f"/api/v1/tasks/{task['task_id']}/archive", json={"story": "长" * 2001}
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "INVALID_INPUT"


def test_date_parse_endpoint_matches_rules(client: TestClient) -> None:
    ok = client.get("/api/v1/date-parse", params={"text": "2021年6月"}).json()
    assert ok["date_sort_key"] == "2021-06-01"
    bad = client.get("/api/v1/date-parse", params={"text": "高三那年"}).json()
    assert bad["date_sort_key"] is None
    assert bad["failed"] is True
    assert "排在最后" in bad["hint"]


def test_legacy_single_page_ui_is_retired(client: TestClient) -> None:
    """阶段 1 那个单 HTML 验收界面已下线（正式前端是 Next.js，独立部署）。

    后端现在只提供 /api/v1/*；根路径返回 404，避免两套界面并存造成误解。
    """
    assert client.get("/").status_code == 404
    assert client.get("/static/accept.js").status_code == 404
