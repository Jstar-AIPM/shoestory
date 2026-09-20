"""多租户隔离（阶段 1 前置的数据契约）：每个身份只能看到自己的鞋柜与任务。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import archive_task, create_task, run_to_artwork


def _switch_owner(client: TestClient, owner_id: str) -> None:
    # 阶段 1–3 的身份来自配置；阶段 4 改为“邀请码 -> owner_id”，此函数即为那个切换点
    client.app.state.container.settings.dev_owner_id = owner_id


def test_two_owners_see_only_their_own_cabinet(client: TestClient) -> None:
    _switch_owner(client, "owner_a")
    task_a = run_to_artwork(client, "kd12")
    created_a = archive_task(client, task_a["task_id"], story="A 的故事")

    _switch_owner(client, "owner_b")
    assert client.get("/api/v1/archive").json()["total"] == 0

    task_b = run_to_artwork(client, "nike pg6")
    created_b = archive_task(client, task_b["task_id"], story="B 的故事")

    list_b = client.get("/api/v1/archive").json()
    assert list_b["total"] == 1
    assert list_b["items"][0]["shoe_id"] == created_b["shoe_id"]
    assert list_b["items"][0]["model_name"] == "Nike PG 6"

    # B 读不到 A 的档案（404，不泄露“存在但无权限”）
    assert client.get(f"/api/v1/archive/{created_a['shoe_id']}").status_code == 404
    assert client.patch(f"/api/v1/archive/{created_a['shoe_id']}", json={"story": "改"}).status_code == 404
    assert client.delete(f"/api/v1/archive/{created_a['shoe_id']}?confirm=true").status_code == 404
    assert client.get(f"/api/v1/archive/{created_a['shoe_id']}/artwork.png").status_code == 404

    # A 的档案在 A 身份下仍然完好
    _switch_owner(client, "owner_a")
    detail_a = client.get(f"/api/v1/archive/{created_a['shoe_id']}").json()
    assert detail_a["story"] == "A 的故事"
    assert client.get("/api/v1/archive").json()["total"] == 1


def test_task_polling_and_actions_are_owner_scoped(client: TestClient) -> None:
    _switch_owner(client, "owner_a")
    task = create_task(client, "kd12")
    task_id = task["task_id"]

    _switch_owner(client, "owner_b")
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 404
    assert client.post(f"/api/v1/tasks/{task_id}/source", json={"selected_index": 0}).status_code == 404
    assert client.post(f"/api/v1/tasks/{task_id}/cancel").status_code == 404
    assert client.post(f"/api/v1/tasks/{task_id}/archive", json={}).status_code == 404
    assert client.get(f"/api/v1/tasks/{task_id}/artworks/1.png").status_code == 404


def test_storage_keys_are_prefixed_by_owner(client: TestClient) -> None:
    _switch_owner(client, "owner_a")
    task = run_to_artwork(client, "kd12")
    created = archive_task(client, task["task_id"])

    backend = client.app.state.container.backend
    keys = backend.list_keys("owners")
    assert any(key.startswith("owners/owner_a/archive.json") for key in keys)
    assert any(key.startswith(f"owners/owner_a/assets/{created['shoe_id']}/artwork.png") for key in keys)
    assert any(key.startswith(f"owners/owner_a/tasks/{task['task_id']}") for key in keys)
    assert any(key.startswith(f"owners/owner_a/traces/trace_{task['task_id']}") for key in keys)
    # 不应写入任何无 owner 前缀的裸 key
    assert not any(key.startswith("archive.json") for key in keys)


def test_same_shoe_id_different_owner_does_not_collide(client: TestClient) -> None:
    _switch_owner(client, "owner_a")
    task_a = run_to_artwork(client, "kd12")
    created_a = archive_task(client, task_a["task_id"])

    _switch_owner(client, "owner_b")
    task_b = run_to_artwork(client, "kd12")
    created_b = archive_task(client, task_b["task_id"])

    assert created_a["shoe_id"] != created_b["shoe_id"]
    backend = client.app.state.container.backend
    assert backend.exists(f"owners/owner_a/assets/{created_a['shoe_id']}/artwork.png")
    assert backend.exists(f"owners/owner_b/assets/{created_b['shoe_id']}/artwork.png")
    assert not backend.exists(f"owners/owner_a/assets/{created_b['shoe_id']}/artwork.png")
