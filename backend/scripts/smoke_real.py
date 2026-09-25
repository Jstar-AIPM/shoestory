#!/usr/bin/env python
"""第二层验收：真实模型端到端冒烟（按约定：无 Key 时如实写"待验"，不冒充通过）。

脚本自己做三件事，全部如实记录：
  1. 拉起真实 uvicorn 服务（不是 mock 进程，真实异步流水线 + 轮询接口）
  2. 用真实 Key 跑完整链路：型号校对 -> 搜图 -> 源图确认 -> 生成 -> 后处理 -> 质检 ->
     效果确认 -> 归档 -> 读回
  3. 把实测结果写成报告：docs/smoke-report-v2-upload.md

用法（在 backend/ 目录下）：
    python scripts/smoke_real.py --query "nike kd 12" --source-index 0

无真实 Key 时：**不会**冒充成功，报告里写“待验”，退出码 2。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.services.cv.binarize import check_artwork  # noqa: E402

RUNNING_STATES = {"resolving", "preprocessing", "generating", "refining", "verifying", "archiving"}


def wait_for_server(base_url: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/v1/health", timeout=3.0)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        time.sleep(0.5)
    raise RuntimeError(f"服务在 {timeout}s 内没有起来（最后一次错误：{last_error}）")


def start_server(port: int) -> tuple[subprocess.Popen, Path]:
    env = dict(os.environ)
    env.setdefault("APP_PORT", str(port))
    env["PIPELINE_INLINE"] = "false"  # 冒烟必须走真实的“后台执行 + 轮询”路径
    log_path = BACKEND_DIR / "data" / "logs" / "smoke_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 注意：这里必须重定向到文件，不能用 subprocess.PIPE ——
    # 管道缓冲区写满后服务会阻塞在写日志上，表现为“任务卡住不返回”。
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_path


def run_flow(
    client: httpx.Client,
    query: str,
    source_index: int | None,
    poll_timeout: float,
    source_path: str | None = None,
) -> dict:
    report: dict = {"query": query, "steps": [], "call_trace": []}

    def step(name: str, started: float, **extra) -> None:
        report["steps"].append({"name": name, "seconds": round(time.perf_counter() - started, 2), **extra})

    started = time.perf_counter()
    response = client.post("/api/v1/tasks", json={"query": query})
    response.raise_for_status()
    task = response.json()
    step("型号校对 + 搜图", started, state=task["state"], normalized=(task.get("normalize") or {}).get("normalized"))
    report["task_id"] = task["task_id"]

    if task["state"] in {"model_not_found", "resolve_failed"}:
        report["conclusion"] = "未通过"
        report["reason"] = f"第一步就失败：state={task['state']}，error={(task.get('error') or {}).get('code')}"
        return report
    report["source_candidates"] = [
        {"index": c["index"], "provider": c["provider"], "size": f"{c.get('width')}x{c.get('height')}"}
        for c in task["source_candidates"]
    ]

    started = time.perf_counter()
    source_mode = task.get("source_mode")
    if source_path:
        # 手动指定源图（用 PM 自己拍的真实球鞋照片）
        payload: dict = {"manual_path": source_path}
        report["source_mode"] = "manual_path"
    elif source_mode == "model_only":
        # 系统预筛判定搜到的图都不适合当参考 -> 走它推荐的“型号直出”（这是产品的默认行为）
        payload = {"use_model_only": True}
        report["source_mode"] = "model_only（系统推荐）"
    else:
        payload = {"selected_index": source_index or 0}
        report["source_mode"] = f"search_candidate（{source_mode}）"
    response = client.post(f"/api/v1/tasks/{task['task_id']}/source", json=payload)
    response.raise_for_status()
    step("选源图并提交生成", started, state=response.json()["state"])

    deadline = time.time() + poll_timeout
    seen_states: list[str] = []
    last = task
    while time.time() < deadline:
        last = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        state = last["state"]
        if not seen_states or seen_states[-1] != state:
            seen_states.append(state)
        if state not in RUNNING_STATES:
            break
        time.sleep(1.5)
    report["states_seen"] = seen_states
    report["final_state"] = last["state"]
    report["upstream_calls"] = last.get("upstream_calls")
    report["est_cost_cny"] = last.get("est_cost_cny")
    report["quality"] = last.get("quality")
    report["error"] = last.get("error")

    if last["state"] not in {"awaiting_effect_confirm", "failed"} or not last.get("artworks"):
        report["conclusion"] = "未通过"
        report["reason"] = f"没有产出画稿：state={last['state']}"
        return report

    report["attempts"] = len(last["artworks"])
    report["passed_first_attempt"] = bool(last["artworks"][0]["passed"])

    started = time.perf_counter()
    artwork = client.get(last["current_artwork_url"])
    artwork.raise_for_status()
    check = check_artwork(artwork.content, 1536, 1024)
    step("取画稿并自检", started, **{"canvas_score": check["canvas_score"]})
    report["artwork_check"] = check

    out_dir = REPO_ROOT / "docs" / "smoke-artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    artwork_path = out_dir / f"{last['task_id']}.png"
    artwork_path.write_bytes(artwork.content)
    report["artwork_path"] = str(artwork_path.relative_to(REPO_ROOT))

    started = time.perf_counter()
    response = client.post(
        f"/api/v1/tasks/{task['task_id']}/archive",
        json={"date_text": "2020", "story": "（冒烟测试写入的示例故事）"},
    )
    response.raise_for_status()
    archived = response.json()
    step("归档", started, shoe_id=archived["shoe_id"])

    listing = client.get("/api/v1/archive").json()
    report["archive_total"] = listing["total"]
    report["archived"] = archived

    ok = (
        check["ratio_ok"]
        and check["binary"]
        and check["background_ok"]
        and (last["state"] == "awaiting_effect_confirm")
    )
    report["conclusion"] = "通过" if ok else "未通过"
    if not ok:
        report["reason"] = "画稿硬指标不合格或状态未到效果确认"
    return report


def write_report(report: dict, provider_info: dict, filename: str = "早期冒烟报告.md") -> Path:
    path = REPO_ROOT / "docs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "# 阶段 1 第二层冒烟报告（真实模型端到端）",
        "",
        f"> 生成时间：{now}",
        f"> 结论：**{report.get('conclusion')}**",
        "",
        "## 环境与模型",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| Provider 模式 | {provider_info.get('mode')} |",
        f"| 文本模型（型号校对） | {provider_info.get('text_model') or '—'} |",
        f"| 视觉模型（质检） | {provider_info.get('vision_model') or '—'} |",
        f"| 图生图模型 | {provider_info.get('image_model') or '—'} |",
        f"| 搜图 | {provider_info.get('search')} |",
        f"| Python | {sys.version.split()[0]} |",
        "",
        "## 链路与耗时",
        "",
        "| 步骤 | 耗时（秒） | 备注 |",
        "| --- | --- | --- |",
    ]
    for step in report.get("steps", []):
        extra = {k: v for k, v in step.items() if k not in {"name", "seconds"}}
        lines.append(f"| {step['name']} | {step['seconds']} | {json.dumps(extra, ensure_ascii=False)} |")
    lines += [
        "",
        f"- 状态轨迹：{' → '.join(report.get('states_seen', [])) or '—'}",
        f"- 最终状态：{report.get('final_state', '—')}",
        f"- 上游调用次数：{report.get('upstream_calls', '—')}",
        f"- 生成次数（含自动重试）：{report.get('attempts', '—')}｜是否**首次即达标**：{report.get('passed_first_attempt', '—')}",
        "",
        "## 质检结果",
        "",
        "```json",
        json.dumps(report.get("quality") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 画稿硬指标（确定性代码判定）",
        "",
        "```json",
        json.dumps(report.get("artwork_check") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    if report.get("artwork_path"):
        lines.append(f"画稿文件：`{report['artwork_path']}`（请人工确认：鞋型/Logo/无文字）")
    if report.get("error"):
        lines.append("")
        lines.append("## 失败信息")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(report["error"], ensure_ascii=False, indent=2))
        lines.append("```")
    if report.get("reason"):
        lines += ["", f"**原因**：{report['reason']}", ""]

    lines += [
        "",
        "## 诚实性声明",
        "",
        "- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。",
        "- mock 结果不会写成本报告的“通过”。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 1 真实模型端到端冒烟")
    parser.add_argument("--query", default="nike kd 12")
    parser.add_argument(
        "--source-index",
        type=int,
        default=None,
        help="用搜图返回的第几张候选图（默认 0）",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        help="手动指定源图路径（搜图未开通时的兑底，文件需在 ALLOWED_SOURCE_DIRS 内）",
    )
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--poll-timeout", type=float, default=600.0)
    parser.add_argument("--report", default="早期冒烟报告.md", help="报告文件名（写到 docs/ 下）")
    args = parser.parse_args()

    settings = Settings()
    container_mode = "mock" if settings.use_mock_providers else "real"
    provider_info = {
        "mode": container_mode,
        "text_model": settings.ark_text_model,
        "vision_model": settings.ark_vision_model,
        "image_model": settings.ark_image_model,
        "search": "real" if settings.search_credentials_present else "mock",
    }

    if container_mode == "mock":
        report = {
            "conclusion": "待验",
            "reason": "未配置 ARK_API_KEY（或强制走 mock），本次没有执行任何真实模型调用。",
            "steps": [],
        }
        path = write_report(report, provider_info, args.report)
        print("=" * 72)
        print("⚠️  冒烟待验：没有拿到真实的火山方舟 Key，未执行任何真实调用。")
        print("    这不是“通过”。请先在 .env 里填好 ARK_API_KEY / ARK_TEXT_MODEL /")
        print("    ARK_VISION_MODEL / ARK_IMAGE_MODEL 后重新运行本脚本。")
        print(f"    报告已写入：{path}")
        print("=" * 72)
        return 2

    base_url = f"http://127.0.0.1:{args.port}"
    print(f"启动真实服务：{base_url}")
    server, server_log = start_server(args.port)
    try:
        health = wait_for_server(base_url)
        provider_info["mode"] = health["providers"]["mode"]
        with httpx.Client(base_url=base_url, timeout=120.0) as client:
            report = run_flow(
                client, args.query, args.source_index, args.poll_timeout, args.source_path
            )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()

    path = write_report(report, provider_info, args.report)
    print(f"\n服务端日志：{server_log}")
    print(f"报告：{path}")
    return 0 if report.get("conclusion") == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
