"""自动重试、成本护栏、以及“不拿 mock 冒充真实”的边界测试。"""

from __future__ import annotations

from tests.conftest import create_task, run_to_artwork


def test_internal_attempts_default_to_two(client_factory) -> None:
    """默认内部最多画 2 张：第 1 张不合格时自动补画 1 张。

    产品原则（2026-09-23）：**不 dead-end** —— 两张都不合格也要把最接近的一张交给用户裁决，
    所以最终状态是 awaiting_effect_confirm（带一句人话说明），而不是 failed。
    """
    with client_factory(mock_quality="low") as client:
        task = run_to_artwork(client, "kd12")
        assert task["state"] == "awaiting_effect_confirm"
        assert len(task["artworks"]) == 2
        assert task["quality"]["verdict"] == "fail"
        assert task["quality"]["note"], "必须给用户一句可读的说明"
        assert task["error"] is None, "交付了图就不该再报错"


def test_retry_mechanism_when_configured_to_three(client_factory) -> None:
    """把 GEN_MAX_ATTEMPTS 配成 3 时，自动重试机制仍然工作（保留该能力以备需要）。"""
    with client_factory(mock_quality="low", gen_max_attempts=3) as client:
        task = run_to_artwork(client, "kd12")
        assert task["state"] == "awaiting_effect_confirm"
        assert len(task["artworks"]) == 3  # 上限 3 次
        assert task["quality"]["issues"], "质检明细仍保留在接口里（供后台排查）"
        assert task["quality"]["note"]
        # 任务级计数：型号校对 1 + 搜图 1 + 源图预筛 1 + （生成 3 + 质检 3）= 9，不超过硬上限
        assert task["upstream_calls"] == 9
        assert task["upstream_calls"] <= 10
        assert task["est_cost_cny"] > 0


def test_good_quality_costs_one_generate_and_one_judge(client: TestClient) -> None:
    task = run_to_artwork(client, "kd12")
    assert task["state"] == "awaiting_effect_confirm"
    # 型号校对 1 + 搜图 1 + 源图预筛 1 + 生成 1 + 质检 1 = 5
    assert task["upstream_calls"] == 5


def test_budget_guard_stops_runaway_calls(client_factory) -> None:
    # 型号校对(1) + 搜图(1) 已用掉 2 次，把上限压到 2 -> 生成阶段必须被拦住
    with client_factory(task_max_upstream_calls=2) as client:
        task = create_task(client, "kd12")
        assert task["state"] == "awaiting_source_confirm"
        client.post(f"/api/v1/tasks/{task['task_id']}/source", json={"selected_index": 0})

        final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        assert final["state"] == "failed"
        assert final["error"]["code"] == "BUDGET_EXCEEDED"
        assert final["upstream_calls"] <= 2
        assert final["artworks"] == []


def test_user_regenerate_starts_a_new_round_and_keeps_history(client_factory) -> None:
    """用户点“重新生成”= 新的一轮（默认 1 张/轮），历史画稿保留可对比。"""
    with client_factory(mock_quality="low", task_max_upstream_calls=20) as client:
        task = run_to_artwork(client, "kd12")
        assert task["state"] == "awaiting_effect_confirm"
        assert len(task["artworks"]) == 2  # 第 1 轮内部画了 2 张

        response = client.post(f"/api/v1/tasks/{task['task_id']}/regenerate", json={"note": "再试一次"})
        assert response.status_code == 202

        final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        assert final["state"] == "awaiting_effect_confirm"  # mock 仍是低分，但照样交给用户裁决
        assert len(final["artworks"]) == 4  # 新一轮又 2 张，历史全部保留
        assert final["upstream_calls"] <= 16

        # 轨迹里记录了“用户为什么重新生成”（未来微调原料）
        from app.core.paths import owner_key
        from app.services.storage.atomic_io import read_jsonl

        container = client.app.state.container
        trace = read_jsonl(
            container.backend, owner_key("owner", "traces", f"trace_{task['task_id']}.jsonl")
        )
        events = [item["event"] for item in trace]
        assert "user_regenerate" in events
        assert "verify_result" in events
        assert any(item.get("note") == "再试一次" for item in trace if item["event"] == "user_regenerate")
