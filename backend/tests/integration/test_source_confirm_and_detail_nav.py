"""源图确认的体验设计（阶段 1 内 PM 反馈后的调整）：

- 系统负责选参考图，用户只回答"是这双吗" → `source_mode=single` 时只给 1 张推荐图；
- 系统没把握（型号置信度低）时才展开多张 → `source_mode=choose`；
- 详情页支持上一双/下一双翻页（后端算好 neighbors）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.llm import ModelCandidate, ModelResolveOut
from tests.conftest import archive_task, create_task, run_to_artwork


class LowConfidenceResolver:
    """测试替身：型号存在但置信度不高 -> 应进入 choose 模式。"""

    name = "stub-low"
    model = "stub-low"
    mode = "mock"

    def resolve(self, raw_query: str, known_brands: list[str], recorder) -> ModelResolveOut:
        recorder.check("text")
        recorder.record("text", provider=self.name, detail={"stub": True})
        return ModelResolveOut(
            normalized="Nike KD 12",
            brand="Nike",
            confidence=0.6,
            exists=True,
            candidates=[ModelCandidate(name="Nike KD 13", reason="相近")],
            note="（stub）置信度不高",
        )


def test_confident_match_shows_single_recommended_image(client: TestClient) -> None:
    task = create_task(client, "kd12")
    assert task["state"] == "awaiting_source_confirm"
    assert task["source_mode"] == "single"          # 只给一张，避免"挑图"歧义
    assert task["recommended_index"] == 0
    assert len(task["source_candidates"]) == 3      # 其余候选仍在，但只作兜底
    assert task["progress"]["label"] == "请确认是这双吗"


def test_low_confidence_match_switches_to_choose_mode(client: TestClient) -> None:
    client.app.state.container.providers.resolver = LowConfidenceResolver()
    task = create_task(client, "kd12")
    assert task["state"] == "awaiting_source_confirm"
    assert task["source_mode"] == "choose"          # 不确定 -> 展开多张让用户判断


def test_confirm_without_index_uses_recommended(client: TestClient) -> None:
    """界面上点「就是这双，开始画」时不传 index，后端应使用推荐图。"""
    task = create_task(client, "kd12")
    response = client.post(f"/api/v1/tasks/{task['task_id']}/source", json={})
    assert response.status_code == 202, response.text
    final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
    assert final["state"] == "awaiting_effect_confirm"
    assert final["selected_index"] == 0


def test_candidate_preview_is_proxied_and_cached(client: TestClient) -> None:
    task = create_task(client, "kd12")
    response = client.get(f"/api/v1/tasks/{task['task_id']}/candidates/0.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")

    backend = client.app.state.container.backend
    assert backend.exists(f"owners/owner/tasks/{task['task_id']}/candidate_0.png")  # 已缓存

    missing = client.get(f"/api/v1/tasks/{task['task_id']}/candidates/9.png")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SOURCE_NOT_FOUND"


def test_detail_returns_prev_next_for_navigation(client: TestClient) -> None:
    first = run_to_artwork(client, "kd12")
    shoe_1 = archive_task(client, first["task_id"], date_text="2019")["shoe_id"]

    second = run_to_artwork(client, "nike pg6")
    shoe_2 = archive_task(client, second["task_id"], date_text="2021年6月")["shoe_id"]

    detail_1 = client.get(f"/api/v1/archive/{shoe_1}?sort=date").json()
    assert detail_1["position"] == 1
    assert detail_1["total"] == 2
    assert detail_1["prev_shoe_id"] is None
    assert detail_1["next_shoe_id"] == shoe_2      # 详情页可以直接翻到下一双

    detail_2 = client.get(f"/api/v1/archive/{shoe_2}?sort=date").json()
    assert detail_2["position"] == 2
    assert detail_2["prev_shoe_id"] == shoe_1
    assert detail_2["next_shoe_id"] is None


def test_detail_without_sort_still_works(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    shoe_id = archive_task(client, task["task_id"])["shoe_id"]
    detail = client.get(f"/api/v1/archive/{shoe_id}").json()
    assert detail["model_name"] == "Nike KD 12"
    # 默认按日期排序，因此总会给出翻页信息（只有一双时两边都是 None）
    assert detail["position"] == 1
    assert detail["total"] == 1
    assert detail["prev_shoe_id"] is None and detail["next_shoe_id"] is None
