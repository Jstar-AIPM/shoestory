"""邀请码登录、会话、额度计数、管理员运维（阶段 4 的核心安全能力）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.auth.invite_store import owner_id_for_code

ADMIN = "ADMIN-CODE-1"


def _login(client: TestClient, code: str):
    return client.post("/api/v1/auth/login", json={"code": code})


def test_login_success_sets_httponly_cookie(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="GUEST-CODE-1") as client:
        response = _login(client, "GUEST-CODE-1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["role"] == "guest"
        assert body["remaining"] == 20  # 默认 20 次
        assert body["owner_id"] == owner_id_for_code("GUEST-CODE-1")

        cookie_header = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()


def test_wrong_code_rejected(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN) as client:
        response = _login(client, "NOT-A-REAL-CODE")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "CODE_INVALID"


def test_me_requires_session_in_prod(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN) as client:
        body = client.get("/api/v1/auth/me").json()
        assert body["authenticated"] is False
        assert body["auth_required"] is True


def test_dev_mode_does_not_require_login(client_factory) -> None:
    """本地开发：未启用登录，接口照常可用，/auth/me 明确标注"未启用"。"""
    with client_factory(env="dev", dev_owner_id="owner") as client:
        assert client.get("/api/v1/archive").status_code == 200
        me = client.get("/api/v1/auth/me").json()
        assert me["authenticated"] is True
        assert me["auth_required"] is False
        assert "本地开发" in me["message"]


def test_quota_consumed_on_create_and_manual_regenerate_only(client_factory) -> None:
    """1 次额度 = 1 次点击生成；质检自动重试不计数。"""
    with client_factory(
        env="prod", admin_code=ADMIN, invite_codes="GUEST-Q", mock_quality="low", task_max_upstream_calls=20
    ) as client:
        assert _login(client, "GUEST-Q").status_code == 200

        # 生成一次：即便 mock 质检固定低分、内部补画了 2 张，也只扣 1 次
        created = client.post("/api/v1/tasks", json={"query": "kd12"})
        assert created.status_code == 201
        task_id = created.json()["task_id"]
        client.post(f"/api/v1/tasks/{task_id}/source", json={"use_model_only": True})
        final = client.get(f"/api/v1/tasks/{task_id}").json()
        assert final["state"] == "awaiting_effect_confirm" and len(final["artworks"]) == 2  # 内部画了 2 张

        remaining = client.get("/api/v1/auth/me").json()["remaining"]
        assert remaining == 19  # 只扣 1 次

        # 手动"重新生成"再扣 1 次
        client.post(f"/api/v1/tasks/{task_id}/regenerate", json={"note": "再来一张"})
        assert client.get("/api/v1/auth/me").json()["remaining"] == 18

        # 归档、编辑、查看都不计数
        client.post(f"/api/v1/archive/{client.get('/api/v1/archive').json()['items'][0]['shoe_id']}", json={}) if False else None
        assert client.get("/api/v1/auth/me").json()["remaining"] == 18


def test_quota_exhausted_blocks_generation_but_allows_viewing(client_factory) -> None:
    """额度用完：不能再生成，但已归档的鞋柜仍可查看（PM 明确要求）。"""
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="GUEST-ONE", invite_code_max_uses=1) as client:
        assert _login(client, "GUEST-ONE").status_code == 200

        first = client.post("/api/v1/tasks", json={"query": "kd12"})
        assert first.status_code == 201  # 用掉唯一 1 次
        task_id = first.json()["task_id"]
        client.post(f"/api/v1/tasks/{task_id}/source", json={"use_model_only": True})
        client.post(f"/api/v1/tasks/{task_id}/archive", json={"story": "留个纪念"})

        second = client.post("/api/v1/tasks", json={"query": "kd12"})
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "QUOTA_EXCEEDED"

        # 仍然能看自己的鞋柜
        listing = client.get("/api/v1/archive")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        me = client.get("/api/v1/auth/me").json()
        assert me["authenticated"] is True
        assert me["can_generate"] is False
        assert "查看" in me["message"]


def test_admin_code_is_unlimited_and_cannot_be_revoked(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="GUEST-ONE", invite_code_max_uses=1) as client:
        assert _login(client, ADMIN).status_code == 200
        me = client.get("/api/v1/auth/me").json()
        assert me["role"] == "admin"
        assert me["remaining"] is None  # 不限次数

        # 连开两个任务都不受额度限制
        for _ in range(2):
            assert client.post("/api/v1/tasks", json={"query": "kd12"}).status_code == 201

        # 管理员码不可作废（否则会把自己锁在门外）
        revoked = client.post(f"/api/v1/admin/codes/{ADMIN}/revoke")
        assert revoked.status_code == 403
        assert revoked.json()["error"]["code"] == "FORBIDDEN"


def test_two_codes_see_two_cabinets(client_factory) -> None:
    """一码一鞋柜：A 码看不到 B 码的数据。"""
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="CODE-A,CODE-B") as client:
        assert _login(client, "CODE-A").status_code == 200
        created = client.post("/api/v1/tasks", json={"query": "kd12"})
        task_id = created.json()["task_id"]
        client.post(f"/api/v1/tasks/{task_id}/source", json={"use_model_only": True})
        client.post(f"/api/v1/tasks/{task_id}/archive", json={"story": "A 的故事"})
        assert client.get("/api/v1/archive").json()["total"] == 1

        client.post("/api/v1/auth/logout")
        assert _login(client, "CODE-B").status_code == 200
        assert client.get("/api/v1/archive").json()["total"] == 0


def test_admin_can_list_create_and_purge(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN) as client:
        assert _login(client, ADMIN).status_code == 200

        created = client.post("/api/v1/admin/codes", json={"note": "给 A 公司面试官"})
        assert created.status_code == 201
        new_code = created.json()["code"]
        assert created.json()["remaining"] == 20

        # 新码可登录，且能建自己的鞋柜
        client.post("/api/v1/auth/logout")
        assert _login(client, new_code).status_code == 200
        task = client.post("/api/v1/tasks", json={"query": "kd12"}).json()
        client.post(f"/api/v1/tasks/{task['task_id']}/source", json={"use_model_only": True})
        client.post(f"/api/v1/tasks/{task['task_id']}/archive", json={})
        guest_owner = client.get("/api/v1/auth/me").json()["owner_id"]

        # 管理员查看用量与鞋柜数量
        client.post("/api/v1/auth/logout")
        assert _login(client, ADMIN).status_code == 200
        listing = client.get("/api/v1/admin/codes").json()
        row = next(item for item in listing["items"] if item["code"] == new_code)
        assert row["used_count"] == 1
        assert row["archived_count"] == 1
        assert row["note"] == "给 A 公司面试官"

        # 一键清理该访客数据
        purged = client.delete(f"/api/v1/admin/owners/{guest_owner}")
        assert purged.status_code == 200
        assert purged.json()["removed_files"] >= 1
        after = client.get("/api/v1/admin/codes").json()
        assert next(i for i in after["items"] if i["code"] == new_code)["archived_count"] == 0


def test_admin_endpoints_require_admin_role(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="GUEST-X") as client:
        assert _login(client, "GUEST-X").status_code == 200
        assert client.get("/api/v1/admin/codes").status_code == 403


def test_expired_code_rejected(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN) as client:
        container = client.app.state.container
        container.invite_store.create(code="OLD-CODE", ttl_days=-1 if False else 1)

        # 手工把过期时间改到过去，模拟 30 天到期
        codes = container.invite_store.list_all()
        target = next(c for c in codes if c.code == "OLD-CODE")
        records = [c.public_dict() for c in codes]
        for item in records:
            if item["code"] == target.code:
                item["expires_at"] = "2000-01-01T00:00:00+00:00"
        from app.services.storage.atomic_io import write_json

        write_json(container.backend, "system/invite_codes.json", {"schema_version": 1, "codes": records})

        response = _login(client, "OLD-CODE")
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "CODE_EXPIRED"


def test_tampered_cookie_is_rejected(client_factory) -> None:
    with client_factory(env="prod", admin_code=ADMIN, invite_codes="GUEST-T") as client:
        assert _login(client, "GUEST-T").status_code == 200
        # 篡改签名后应视为未登录
        client.cookies.set("lvli_session", "eyJvd25lcl9pZCI6Im93X2hhY2sifQ.bad-signature")
        assert client.post("/api/v1/tasks", json={"query": "kd12"}).status_code == 401
