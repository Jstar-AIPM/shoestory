#!/usr/bin/env python
"""V2 验收：上传图链路真实模型端到端冒烟（体检 → 生成 → 质检 → 归档）。

为什么单独一个脚本：V1 的 `smoke_real.py` 走的是「型号 → 搜图 → 参考图」，
V2 的入口是「上传一张图」，前置多了一步**体检**（是否鞋 / 品牌型号 / Logo / 文字），
而且坐标约定（EXIF 摆正 + 缩图换算）是 V2 特有的静默风险点 —— 都要真图实测。

脚本自己做的事，全部如实记录：
  1. 拉起真实 uvicorn 服务（真实异步流水线 + 轮询，不是 mock 进程）
  2. 用真实 Key 跑：/inspect（CV 建议框，）→ /inspect（裁切后 AI 体检，约 ）
     → /tasks/upload → 轮询 → 取画稿 + 硬指标自检 → 归档 → 读回
  3. 顺带自检 V2 的坐标约定：`/inspect` 报的图尺寸必须等于**摆正后**的真实图尺寸
     （EXIF 摆正 + 缩图换算一旦漏了，这里就会报不一致 —— 而线上表现是"裁错位置"，不报错）
  4. 把实测结果写成报告：docs/smoke-report-v2-upload.md

用法（在 backend/ 目录下）：
    python scripts/smoke_upload.py --image "/path/to/shoe.jpg"
    python scripts/smoke_upload.py --image "/path/to/shoe.jpg" --crop 120,480,1600,900
    python scripts/smoke_upload.py --image shoe.jpg --base-url https://<线上后端> --admin-code XXX

无真实 Key 时：**不会**冒充成功，报告里写"待验"，退出码 2。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import Settings  # noqa: E402
from app.services.cv.binarize import check_artwork  # noqa: E402
from app.services.cv.imageio import open_image_upright  # noqa: E402
from smoke_real import start_server, wait_for_server  # noqa: E402

RUNNING_STATES = {"preprocessing", "generating", "refining", "verifying", "archiving"}
ARTWORK_W, ARTWORK_H = 1536, 1024


def _upright_size(image_path: Path) -> tuple[int, int]:
    """按浏览器的方式看这张图（应用 EXIF 方向）—— 与 /inspect 报的尺寸比对用。"""
    return open_image_upright(image_path.read_bytes()).size


def run_flow(
    client: httpx.Client,
    image_path: Path,
    crop_arg: tuple[int, int, int, int] | None,
    poll_timeout: float,
    archive: bool,
    forced_mock: bool = False,
) -> dict:
    report: dict = {"image": str(image_path), "steps": [], "checks": {}}

    def step(name: str, started: float, **extra) -> None:
        report["steps"].append({"name": name, "seconds": round(time.perf_counter() - started, 2), **extra})

    raw = image_path.read_bytes()
    encoded = base64.b64encode(raw).decode()
    expect_w, expect_h = _upright_size(image_path)
    report["image_bytes"] = len(raw)
    report["image_size_upright"] = f"{expect_w}x{expect_h}"

    # ---------- ① 只跑 CV：拿建议裁切框（本机计算） ----------
    started = time.perf_counter()
    response = client.post("/api/v1/inspect", json={"image_base64": encoded})
    response.raise_for_status()
    first = response.json()
    step("体检·CV 定位（本机计算）", started, tier=first["tier"], subject=first["subject"])

    reported = f"{first['image']['width']}x{first['image']['height']}"
    report["checks"]["size_contract"] = reported == f"{expect_w}x{expect_h}"
    report["image_size_reported"] = reported
    if not crop_arg and first.get("crop"):
        crop_arg = (first["crop"]["x"], first["crop"]["y"], first["crop"]["w"], first["crop"]["h"])
    if crop_arg is None:
        report["conclusion"] = "未通过"
        report["reason"] = "CV 没给出建议框，且没有用 --crop 指定；无法继续体检。"
        return report
    report["crop"] = list(crop_arg)

    # ---------- ② 裁切后 AI 体检（本机计算） ----------
    started = time.perf_counter()
    response = client.post(
        "/api/v1/inspect",
        json={
            "image_base64": encoded,
            "crop": {"x": crop_arg[0], "y": crop_arg[1], "w": crop_arg[2], "h": crop_arg[3]},
        },
    )
    response.raise_for_status()
    inspected = response.json()
    step(
        "体检·AI 识别（本机计算）",
        started,
        tier=inspected["tier"],
        display_name=inspected["detail"]["display_name"],
        logo=inspected["detail"]["logo_type"],
        texts=inspected["detail"]["texts"],
    )
    report["inspect"] = inspected
    if inspected["tier"] not in {"ok", "uncertain"}:
        report["conclusion"] = "未通过"
        report["reason"] = f"体检判定不能画：tier={inspected['tier']}，message={inspected['message']}"
        return report

    # ---------- ③ 建任务（上传图路径，不再二次调视觉模型） ----------
    started = time.perf_counter()
    response = client.post(
        "/api/v1/tasks/upload",
        json={
            "image_base64": encoded,
            "crop": {"x": crop_arg[0], "y": crop_arg[1], "w": crop_arg[2], "h": crop_arg[3]},
            "inspect": {
                "display_name": inspected["detail"]["display_name"],
                "brand": inspected["detail"]["brand"],
                "model_name": inspected["detail"]["model_name"],
                "colorway": inspected["detail"]["colorway"],
                "logo_type": inspected["detail"]["logo_type"],
                "logo_position": inspected["detail"]["logo_position"],
                "logo_fill_required": inspected["detail"]["logo_fill_required"],
                "texts": inspected["detail"]["texts"],
                "text_stamps": inspected["detail"]["text_stamps"],
                "shoe_count": inspected["detail"]["shoe_count"],
            },
        },
    )
    response.raise_for_status()
    task = response.json()
    task_id = task["task_id"]
    report["task_id"] = task_id
    report["query"] = task["query"]
    step("建任务（上传图）", started, state=task["state"], archive_name=task["query"])

    # ---------- ④ 轮询到出图；顺便验一次 CV 草稿（生成动效要用） ----------
    deadline = time.time() + poll_timeout
    seen_states: list[str] = []
    draft_ok = False
    last = task
    while time.time() < deadline:
        last = client.get(f"/api/v1/tasks/{task_id}").json()
        state = last["state"]
        if not seen_states or seen_states[-1] != state:
            seen_states.append(state)
        if not draft_ok and last.get("draft_url"):
            draft = client.get(last["draft_url"])
            draft_ok = draft.status_code == 200 and draft.headers.get("content-type") == "image/png"
        if state not in RUNNING_STATES:
            break
        time.sleep(1.5)
    report["states_seen"] = seen_states
    report["final_state"] = last["state"]
    report["checks"]["draft_available"] = draft_ok
    report["upstream_calls"] = last.get("upstream_calls")
    report["est_cost_cny"] = last.get("est_cost_cny")
    report["quality"] = last.get("quality")
    report["error"] = last.get("error")
    report["attempts"] = len(last.get("artworks") or [])
    report["passed_first_attempt"] = bool((last.get("artworks") or [{}])[0].get("passed"))

    if last["state"] not in {"awaiting_effect_confirm", "failed"} or not last.get("artworks"):
        report["conclusion"] = "未通过"
        report["reason"] = f"没有产出画稿：state={last['state']}"
        return report

    # ---------- ⑤ 取画稿 + 硬指标自检 ----------
    started = time.perf_counter()
    artwork = client.get(last["current_artwork_url"])
    artwork.raise_for_status()
    check = check_artwork(artwork.content, ARTWORK_W, ARTWORK_H)
    step("取画稿并自检", started, canvas_score=check["canvas_score"])
    report["artwork_check"] = check

    out_dir = REPO_ROOT / "docs" / "smoke-artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    artwork_path = out_dir / f"{task_id}.png"
    artwork_path.write_bytes(artwork.content)
    report["artwork_path"] = str(artwork_path.relative_to(REPO_ROOT))

    # ---------- ⑥ 归档 + 读回 ----------
    if archive:
        started = time.perf_counter()
        response = client.post(
            f"/api/v1/tasks/{task_id}/archive",
            json={"date_text": "2020", "story": "（V2 冒烟测试写入的示例故事）"},
        )
        response.raise_for_status()
        archived = response.json()
        step("归档", started, shoe_id=archived["shoe_id"], model_name=archived.get("model_name"))
        report["archived"] = archived
        report["archive_total"] = client.get("/api/v1/archive").json()["total"]

    if forced_mock:
        # 诚实性底线：mock 跑得再顺也不能写成"通过"
        report["conclusion"] = "演示模式（未验收）"
        report["reason"] = "强制 mock 上游：本次只验证脚本与链路能跑通，mock 结果不构成验收证据。"
        return report

    ok = (
        check["ratio_ok"]
        and check["binary"]
        and check["background_ok"]
        and last["state"] == "awaiting_effect_confirm"
        and report["checks"]["size_contract"]
        and report["checks"]["draft_available"]
    )
    report["conclusion"] = "通过" if ok else "未通过"
    if not ok:
        failed = [k for k, v in report["checks"].items() if not v]
        report["reason"] = (
            f"画稿硬指标不合格或状态未到效果确认（不通过的检查项：{failed or '无，检查状态与画稿'}）"
        )
    return report


def write_report(report: dict, provider_info: dict, filename: str = "smoke-report-v2-upload.md") -> Path:
    path = REPO_ROOT / "docs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）",
        "",
        f"> 生成时间：{now}",
        f"> 结论：**{report.get('conclusion')}**",
        f"> 输入图：`{report.get('image')}`（{report.get('image_size_upright', '—')}，{report.get('image_bytes', 0) // 1024} KB）",
        "",
        "## 环境与模型",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| Provider 模式 | {provider_info.get('mode')} |",
        f"| 视觉模型（体检 / 质检） | {provider_info.get('vision_model') or '—'} |",
        f"| 图生图模型 | {provider_info.get('image_model') or '—'} |",
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
        f"- 归档标题（体检识别）：{report.get('query', '—')}",
        f"- 上游调用次数：{report.get('upstream_calls', '—')}｜上游调用：{report.get('est_cost_cny', '—')}",
        f"- 生成次数（含自动重试）：{report.get('attempts', '—')}｜是否**首次即达标**：{report.get('passed_first_attempt', '—')}",
        "",
        "## V2 特有自检（坐标约定与动效素材）",
        "",
        "| 检查项 | 结果 | 含义 |",
        "| --- | --- | --- |",
    ]
    checks = report.get("checks") or {}
    lines.append(
        f"| 坐标系一致（EXIF 摆正 + 缩图换算） | {'✅' if checks.get('size_contract') else '❌'} "
        f"| /inspect 报的尺寸 {report.get('image_size_reported', '—')} 必须等于摆正后的真实尺寸 "
        f"{report.get('image_size_upright', '—')}；不一致 = 会静默裁错位置 |"
    )
    lines.append(
        f"| CV 草稿可用（生成动效） | {'✅' if checks.get('draft_available') else '❌'} | `draft.png` 应返回 200 + image/png |"
    )
    lines += [
        "",
        "## 体检结论（第③步 AI 识别的原文）",
        "",
        "```json",
        json.dumps(
            {
                "tier": (report.get("inspect") or {}).get("tier"),
                "message": (report.get("inspect") or {}).get("message"),
                "detail": (report.get("inspect") or {}).get("detail"),
                "subject": (report.get("inspect") or {}).get("subject"),
                "crop": report.get("crop"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
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
        lines.append(
            f"画稿文件：`{report['artwork_path']}`（请人工确认三件事：鞋型像不像 / Logo 是否**实心** / "
            "鞋带有没有被涂成黑块）"
        )
    if report.get("error"):
        lines += ["", "## 失败信息", "", "```json", json.dumps(report["error"], ensure_ascii=False, indent=2), "```"]
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
    parser = argparse.ArgumentParser(description="V2 上传图真实模型端到端冒烟")
    parser.add_argument("--image", required=True, help="本机球鞋图路径（仓储内不含真实品牌图，请传本机文件）")
    parser.add_argument("--crop", default=None, help="手动指定裁切框 x,y,w,h（默认用 CV 建议框）")
    parser.add_argument("--base-url", default=None, help="对已有服务跑（例如线上后端地址）；不传则本地拉起服务")
    parser.add_argument("--admin-code", default=None, help="线上/生产模式下的管理员码（也可用环境变量 LVLI_ADMIN_CODE）")
    parser.add_argument("--poll-timeout", type=float, default=600.0)
    parser.add_argument("--no-archive", action="store_true", help="只跑到出图，不做归档")
    parser.add_argument(
        "--force-mock",
        action="store_true",
        help="强制用 mock 上游跑一遍（，用来验证脚本本身能通）—— 结果一律记作未验收",
    )
    parser.add_argument("--report", default="smoke-report-v2-upload.md", help="报告文件名（写到 docs/ 下）")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser()
    if not image_path.is_file():
        print(f"❌ 找不到图片：{image_path}")
        return 1
    crop = None
    if args.crop:
        parts = [int(p) for p in args.crop.split(",")]
        if len(parts) != 4:
            print("❌ --crop 需要 4 个整数：x,y,w,h")
            return 1
        crop = (parts[0], parts[1], parts[2], parts[3])

    settings = Settings()
    mode = "mock" if settings.use_mock_providers else "real"
    provider_info = {
        "mode": mode,
        "vision_model": settings.ark_vision_model,
        "image_model": settings.ark_image_model,
    }

    if mode == "mock" and not args.base_url and not args.force_mock:
        report = {
            "conclusion": "待验",
            "reason": "未配置 ARK_API_KEY（或强制走 mock），本次没有执行任何真实模型调用。",
            "steps": [],
            "image": str(image_path),
        }
        path = write_report(report, provider_info, args.report)
        print("=" * 72)
        print("⚠️  V2 冒烟待验：没有拿到真实的火山方舟 Key，未执行任何真实调用。")
        print("    这不是“通过”。请先在 .env 里填好 ARK_API_KEY 后重新运行本脚本。")
        print("    （只想验证脚本本身能跑通：加 --force-mock，不会被当成验收。）")
        print(f"    报告已写入：{path}")
        print("=" * 72)
        return 2

    server: subprocess.Popen | None = None
    server_log: Path | None = None
    base_url = args.base_url
    if not base_url:
        port = 8898
        base_url = f"http://127.0.0.1:{port}"
        if args.force_mock:
            os.environ["FORCE_MOCK_PROVIDER"] = "true"
            print("⚠️  强制 mock 上游：本次只验证脚本与链路能跑通，结果不得当作验收。")
        print(f"启动真实服务：{base_url}")
        server, server_log = start_server(port)

    try:
        health = wait_for_server(base_url)
        provider_info["mode"] = health["providers"]["mode"]
        timeout = httpx.Timeout(180.0, connect=15.0)
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            admin_code = args.admin_code or os.environ.get("LVLI_ADMIN_CODE")
            # 生产（env=prod）才有登录门；本地 dev 直接是 DEV_OWNER_ID
            if health.get("env") == "prod" or admin_code:
                if not admin_code:
                    print("❌ 该服务需要登录：请用 --admin-code 或环境变量 LVLI_ADMIN_CODE 提供管理员码。")
                    return 1
                login = client.post("/api/v1/auth/login", json={"code": admin_code})
                login.raise_for_status()
                print(f"已登录：{login.json().get('message')}")
            report = run_flow(
                client, image_path, crop, args.poll_timeout, not args.no_archive, args.force_mock
            )
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()

    path = write_report(report, provider_info, args.report)
    if server_log:
        print(f"\n服务端日志：{server_log}")
    print(f"报告：{path}")
    if args.force_mock:
        print("结论：演示模式（未验收）—— mock 结果不构成验收证据。")
        return 2
    print(f"结论：{report.get('conclusion')}")
    return 0 if report.get("conclusion") == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
