#!/usr/bin/env python
"""把线上鞋柜拉回本地，当作离线质量评测的数据集。

## 为什么需要这个脚本

评测"画得像不像 / 该填的填了没有 / 轮廓有没有崩"，必须用**真实的上传图 +
真实生成的画稿**，而不是从截图里猜哪张是原图。线上对象存储里正好完整地存着：

| 文件 | 是什么 |
| --- | --- |
| `source_0.png` | 用户原始上传的图 |
| `canvas_3x2.png` | 预处理后的 3:2 白底画布 —— **就是喂给生图模型的那张** |
| `edge_map.png` | 骨架参考图（当前是裸 Canny） |
| `raw_a{n}.png` | 第 n 次生成的**原始返回**（未经二值化） |
| `artwork_a{n}.png` | 第 n 次生成**后处理完**的稿子（就是用户看到的那张） |
| `tasks/<id>.json` | 任务记录：体检结论、逐项质检分、风格度量、用了第几次 |

另一条更省事的路径是直接调线上接口，但接口拿不到源图；而对象存储里全都有。
所以这里直连 TOS 读。**不花任何模型费用**。

## 安全边界（重要，改这个脚本前先读）

1. **只读**：只用 `list_keys` / `get_bytes`，没有任何写操作；
2. **只碰管理员自己的 owner 命名空间**：一码一鞋柜是隐私承诺，脚本会先校验
   `ow_` 前缀来自管理员码，绝不去列别的 owner；
3. **不打印邀请码**：码从环境变量 / `.env` / `--code-file` 读，全程不回显。

## 用法

    export LVLI_ADMIN_CODE="LVLI-ADMIN-XXXXXX"
    cd backend
    python scripts/pull_live_dataset.py --out "../../·质量评测/dataset"

    # 只要某几个任务
    python scripts/pull_live_dataset.py --out ... --task tk_20260923T142615_xxxx

    # 干跑：只列要拉什么，不落盘
    python scripts/pull_live_dataset.py --out ... --dry-run

输出目录（默认建议放在以 `·` 开头的目录下 —— 那些目录已被 .gitignore 挡住，
因为里面是真实品牌商品图，不入仓库）：

    <out>/
      manifest.json            # 索引：每双鞋 ↔ 任务 ↔ 归档 ↔ 文件清单
      archive.json             # 线上归档文件原文
      tasks/<task_id>.json     # 每个任务的完整记录
      items/<序号>__<task_id>/
          source_0.png  canvas_3x2.png  edge_map.png
          raw_a1.png …  artwork_a1.png …
          meta.json            # 从任务记录里摘出来的评测相关字段
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.services.auth.invite_store import owner_id_for_code  # noqa: E402
from app.services.storage.s3_backend import S3Backend  # noqa: E402

#: 每个任务里值得拉下来做评测的文件前缀（其余是候选图/中间件，评测用不上）
KEEP_PREFIXES = ("source_0", "canvas_3x2", "edge_map", "raw_a", "artwork_a", "cutout")


def _read_admin_code(args: argparse.Namespace) -> str:
    """按 环境变量 → --code-file → 仓库根 .env 的顺序找管理员码；找不到就明确报错。"""
    code = os.environ.get("LVLI_ADMIN_CODE", "").strip()
    if code:
        return code
    if args.code_file:
        text = Path(args.code_file).read_text(encoding="utf-8")
        found = re.search(r"LVLI-ADMIN-[A-Z0-9]+", text)
        if found:
            return found.group(0)
        raise SystemExit(f"--code-file 里没找到管理员码：{args.code_file}")
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ADMIN_CODE="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise SystemExit(
        "没拿到管理员码。请设置环境变量 LVLI_ADMIN_CODE，或用 --code-file 指向本机凭据文件。"
    )


def _task_meta(record: dict) -> dict:
    """从任务记录里摘出评测关心的字段（保持原样，不做解释，避免二手信息）。"""
    inspect = record.get("inspect") or {}
    quality = record.get("quality") or {}
    return {
        "task_id": record.get("task_id"),
        "state": record.get("state"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "style_id": record.get("style_id"),
        "attempts": record.get("attempts"),
        "upstream_calls": record.get("upstream_calls"),
        # 体检结论：品牌/型号/Logo/可见性/文字
        "inspect": {
            "display_name": inspect.get("display_name"),
            "brand": inspect.get("brand"),
            "model_name": inspect.get("model_name"),
            "logo_type": inspect.get("logo_type"),
            "logo_position": inspect.get("logo_position"),
            "logo_fill_required": inspect.get("logo_fill_required"),
            "texts": inspect.get("texts"),
            "shoe_count": inspect.get("shoe_count"),
        },
        # 质检：逐项分数 + best attempt + 风格度量（artwork_check.style_metrics）
        "quality": {
            "score": quality.get("score"),
            "attempts": quality.get("attempts"),
            "checks": quality.get("checks"),
            "issues": quality.get("issues"),
            "verdict": quality.get("verdict"),
            "best_attempt": quality.get("best_attempt"),
            "artwork_check": quality.get("artwork_check"),
        },
        "artworks": [
            {
                "attempt": item.get("attempt"),
                "path": item.get("path"),
                "score": item.get("score"),
                "passed": item.get("passed"),
                "issues": item.get("issues"),
            }
            for item in record.get("artworks") or []
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="把线上鞋柜拉回本地做离线评测")
    parser.add_argument("--out", required=True, help="输出目录（建议放在以 · 开头的目录下）")
    parser.add_argument("--code-file", default="", help="管理员码所在文件（默认读 .env 的 ADMIN_CODE）")
    parser.add_argument("--task", action="append", default=[], help="只拉指定 task_id，可重复")
    parser.add_argument("--dry-run", action="store_true", help="只列要拉的文件，不写盘")
    args = parser.parse_args()

    admin_code = _read_admin_code(args)
    owner = owner_id_for_code(admin_code)

    settings = Settings()
    settings.storage_provider = "s3"  # 这个脚本永远读线上，不受 .env 的 local 影响
    backend = S3Backend(settings)

    print(f"管理员 owner：{owner}")
    keys = backend.list_keys(f"owners/{owner}/")
    if not keys:
        print("这个 owner 下没有任何对象（鞋柜是空的？）")
        return 1

    # 二次确认：我们只在自己这个 owner 的命名空间里活动
    assert all(k.startswith(f"owners/{owner}/") for k in keys), "越界：出现了别的 owner"

    task_jsons = sorted(k for k in keys if k.startswith(f"owners/{owner}/tasks/") and k.endswith(".json"))
    archive_key = f"owners/{owner}/archive.json"
    print(f"任务记录 {len(task_jsons)} 个；归档文件{'在' if archive_key in keys else '不在'}")

    tasks: list[dict] = []
    for key in task_jsons:
        record = json.loads(backend.get_bytes(key).decode("utf-8"))
        if args.task and record.get("task_id") not in args.task:
            continue
        task_id = record.get("task_id") or Path(key).stem
        files = sorted(
            k for k in keys
            if k.startswith(f"owners/{owner}/tasks/{task_id}/")
            and Path(k).name.startswith(KEEP_PREFIXES)
        )
        # 没有 source_0.png 的（V1 型号直出、或半途失败的任务）不进评测集
        has_source = any(Path(k).name == "source_0.png" for k in files)
        tasks.append({"task_id": task_id, "key": key, "files": files, "has_source": has_source,
                      "record": record})

    usable = [t for t in tasks if t["has_source"]]
    print(f"可进评测集（有上传源图）的任务：{len(usable)} / {len(tasks)}")

    if args.dry_run:
        for index, task in enumerate(usable, 1):
            print(f"\n[{index}] {task['task_id']}")
            for key in task["files"]:
                print("      ", key.split(f"/{task['task_id']}/")[-1])
        return 0

    out = Path(args.out).expanduser().resolve()
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    (out / "items").mkdir(parents=True, exist_ok=True)

    if archive_key in keys:
        (out / "archive.json").write_bytes(backend.get_bytes(archive_key))
    else:
        (out / "archive.json").write_text('{"schema_version": 1, "items": []}', encoding="utf-8")

    manifest: list[dict] = []
    for index, task in enumerate(usable, 1):
        task_id = task["task_id"]
        folder = out / "items" / f"{index:02d}__{task_id}"
        folder.mkdir(parents=True, exist_ok=True)
        (out / "tasks" / f"{task_id}.json").write_bytes(backend.get_bytes(task["key"]))

        saved: list[str] = []
        for key in task["files"]:
            name = Path(key).name
            (folder / name).write_bytes(backend.get_bytes(key))
            saved.append(name)

        meta = _task_meta(task["record"])
        (folder / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest.append({"index": index, "task_id": task_id, "folder": folder.name,
                         "files": saved, "meta": meta})
        label = (meta["inspect"] or {}).get("display_name") or "?"
        print(f"  [{index:02d}] {label:<28} {task_id}  ({len(saved)} 个文件)")

    (out / "manifest.json").write_text(
        json.dumps({"owner": owner, "count": len(manifest), "items": manifest},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n完成 → {out}")
    print("下一步：python scripts/quality_eval.py --dataset <这个目录>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
