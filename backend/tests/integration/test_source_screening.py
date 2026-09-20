"""候选源图预筛：决定"只推 1 张"还是"展开多张"，并且失败不阻塞。

背景（真实实测）：文搜图返回的常是"两只鞋合影 / 3⁄4 角度 / 背景杂乱"的资讯配图，
直接推荐给用户会让线稿偏离规范。因此推荐前先用一次视觉调用判可用性。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.llm import SourceScreenItem, SourceScreenOut
from tests.conftest import create_task


def all_bad_screener(recorder):
    """所有候选图都判为不可用（模拟文搜图的真实情况）。"""
    recorder.check("vision")
    recorder.record("vision", provider="stub-screen", detail={"stub": True})
    return SourceScreenOut(
        results=[
            SourceScreenItem(
                index=index,
                single_shoe=False,
                side_view=False,
                clean_background=False,
                sharp=True,
                score=0.2,
                reason="两只鞋的合影且为 3/4 角度",
            )
            for index in range(len(recorder.images))  # type: ignore[attr-defined]
        ],
        best_index=-1,
    )


def patch_screener(monkeypatch, container, fn) -> None:
    """只替换“预筛”这一步，质检能力保持原样（两件事不要混在一起）。"""

    def wrapped(*, images, model_name, recorder):
        recorder.images = images  # type: ignore[attr-defined]
        try:
            return fn(recorder)
        finally:
            pass

    monkeypatch.setattr(container.providers.judge, "screen_sources", wrapped)


def broken_screener(recorder):
    from app.core.errors import AppError, ErrorCode

    recorder.check("vision")
    recorder.record("vision", provider="stub-broken", ok=False, error_code="UPSTREAM_ERROR")
    raise AppError(ErrorCode.UPSTREAM_ERROR)


def test_good_candidate_keeps_single_mode_with_reason(client: TestClient) -> None:
    task = create_task(client, "kd12")
    assert task["state"] == "awaiting_source_confirm"
    assert task["source_mode"] == "single"  # mock 预筛第 1 张可用
    first = task["source_candidates"][0]
    assert first["screen_score"] == 0.9
    assert "单只" in first["screen_reason"]


def test_all_bad_candidates_switch_to_choose_mode(client: TestClient, monkeypatch) -> None:
    container = client.app.state.container
    patch_screener(monkeypatch, container, all_bad_screener)
    task = create_task(client, "kd12")
    # 没有一张适合当参考 -> 默认引导"直接用型号生成"（实测保真度更高），而不是硬推一张坏图
    assert task["source_mode"] == "model_only"
    assert all(c["screen_score"] == 0.2 for c in task["source_candidates"])


def test_screening_failure_falls_back_without_blocking(client: TestClient, monkeypatch) -> None:
    container = client.app.state.container
    patch_screener(monkeypatch, container, broken_screener)
    task = create_task(client, "kd12")
    assert task["state"] == "awaiting_source_confirm"  # 主链路不受影响
    assert task["source_mode"] == "single"  # 退回启发式排序

    from app.core.paths import owner_key
    from app.services.storage.atomic_io import read_jsonl

    trace = read_jsonl(
        container.backend, owner_key("owner", "traces", f"trace_{task['task_id']}.jsonl")
    )
    assert any(item["event"] == "source_screen_failed" for item in trace)


def test_screening_can_be_disabled(client_factory) -> None:
    with client_factory(enable_source_screening=False) as client:
        task = create_task(client, "kd12")
        assert task["state"] == "awaiting_source_confirm"
        assert task["source_candidates"][0].get("screen_score") is None


def test_model_only_fallback_path(client_factory, monkeypatch) -> None:
    """候选图都不可用时，用户可以选「直接用型号生成」：跳过预处理、无参考图生成。"""
    with client_factory(mock_quality="good") as client:
        container = client.app.state.container
        patch_screener(monkeypatch, container, all_bad_screener)
        task = create_task(client, "kd12")
        assert task["source_mode"] == "model_only"

        response = client.post(
            f"/api/v1/tasks/{task['task_id']}/source", json={"use_model_only": True}
        )
        assert response.status_code == 202, response.text

        final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        # mock 质检固定低分 -> 会走到 failed；关键是链路走通了（有画稿产出）
        assert final["state"] in {"awaiting_effect_confirm", "failed"}
        assert final["artworks"], final

    from app.core.paths import owner_key
    from app.services.storage.atomic_io import read_jsonl

    trace = read_jsonl(
        client.app.state.container.backend,
        owner_key("owner", "traces", f"trace_{task['task_id']}.jsonl"),
    )
    assert any(item["event"] == "model_only_generation" for item in trace)


def test_model_only_works_even_when_search_returns_nothing(client: TestClient) -> None:
    """搜图 0 结果时，用户仍必须能继续（否则"型号存在但没图"会让人无路可走）。"""
    from tests.conftest import EmptySearchProvider

    client.app.state.container.providers.search = EmptySearchProvider()
    task = create_task(client, "kd12")
    assert task["state"] == "resolve_failed"

    response = client.post(f"/api/v1/tasks/{task['task_id']}/source", json={"use_model_only": True})
    assert response.status_code == 202, response.text

    final = client.get(f"/api/v1/tasks/{task['task_id']}").json()
    assert final["state"] in {"awaiting_effect_confirm", "failed"}
    assert final["artworks"], final


def test_request_rejects_conflicting_source_options(client: TestClient) -> None:
    task = create_task(client, "kd12")
    response = client.post(
        f"/api/v1/tasks/{task['task_id']}/source",
        json={"selected_index": 0, "use_model_only": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
