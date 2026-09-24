#!/usr/bin/env python
"""质量评测台的「重新生成」模式：用当前规则重画整批鞋，并给出前后对比。

## 为什么需要它（而不是复用 smoke_upload.py）

`smoke_upload.py` 走 HTTP 上传入口，而 `/inspect` 要求图片至少 400×400 ——
线上留下的一批源图里，大多数是**用户裁切后**的尺寸（例如 710×387），直接被拒。
结果是"最该验证的那几张反而验证不了"。

这个模式绕开 HTTP 层，**直接调生产链路的同一套代码**：
    读源图 → AI 体检 → segment / normalize / edge 预处理 → 生成 → 质检 →（按原因）重画
用的是 `PipelineRunner` 与 `StyleRegistry` 本身，不是另写一套 —— 所以它验证的是真代码。

产出：一批新画稿 + 一张"旧稿 vs 新稿"并排对比图 + 明细 JSON，用来回答
"规则改了之后，这双鞋到底变好没有"。

## 用法

    cd backend
    python scripts/quality_regen.py --dataset "../../·质量评测/dataset" \\
        --out "../../·质量评测/after" --only 11,14,15,16,22,24

⚠️ 会真实调用上游模型并产生费用（每张最多 2 次生成）。先想清楚要测哪几张。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.core.config import STYLES_DIR, Settings  # noqa: E402
from app.core.idgen import new_task_id, new_trace_id, now_iso  # noqa: E402
from app.schemas.enums import TaskState  # noqa: E402
from app.schemas.task import InspectHints, TaskRecord  # noqa: E402
from app.services.providers.base import CallRecorder, build_providers  # noqa: E402
from app.services.storage.asset_store import AssetStore  # noqa: E402
from app.services.storage.backend import build_backend  # noqa: E402
from app.services.storage.task_store import TaskStore  # noqa: E402
from app.services.style.registry import StyleRegistry  # noqa: E402
from app.services.workflow.runner import SOURCE_FILENAME, PipelineRunner  # noqa: E402

THUMB_H = 240


def _inspect_hints(providers, recorder: CallRecorder, image_bytes: bytes) -> InspectHints:
    """跑一次真实体检，拿到含 `logo_visibility` 的结论（新链路的关键输入）。

    用整图，不裁切：数据集里的 `source_0.png` 已经是用户当初确认过的裁切结果。
    """
    vision = providers.judge.inspect_photo(image=image_bytes, recorder=recorder)
    return InspectHints(
        display_name=vision.display_name,
        brand=vision.brand,
        model_name=vision.model_name,
        colorway=vision.colorway,
        logo_type=vision.logo.type,
        logo_position=vision.logo.position,
        logo_visibility=vision.logo.visibility,
        logo_fill_required=vision.logo.fill_required,
        texts=vision.drawable_texts,
        shoe_count=max(1, vision.shoe_count),
    )


def regenerate(
    source_png: Path,
    *,
    data_dir: Path,
    out_dir: Path,
    style_id: str = "",
    owner_id: str = "eval",
) -> dict:
    """用当前规则把一张源图重画一遍。返回结果（画稿路径、质检、体检结论）。

    `data_dir` 用临时目录 —— 评测不该污染本地开发数据；画稿会另存一份到 `out_dir`。
    """
    settings = Settings(
        data_dir=str(data_dir),
        storage_provider="local",
        dev_owner_id=owner_id,
    )
    backend = build_backend(settings)
    providers = build_providers(settings)
    task_store = TaskStore(backend)
    asset_store = AssetStore(backend)

    raw = source_png.read_bytes()
    hints = _inspect_hints(providers, CallRecorder(settings.task_max_upstream_calls, settings), raw)

    task_id = new_task_id()
    record = TaskRecord(
        task_id=task_id,
        owner_id=owner_id,
        state=TaskState.PREPROCESSING,
        created_at=now_iso(),
        updated_at=now_iso(),
        style_id=style_id or settings.style_id,
        query=hints.name_for_archive or "评测",
        inspect=hints,
        trace_id=new_trace_id(),
    )
    task_store.create(record)
    # 源图 = 数据集里那张（用户当初确认过的裁切结果），与线上一致
    asset_store.put_task_file(owner_id, task_id, SOURCE_FILENAME, raw)
    task_store.save(record)

    runner = PipelineRunner(
        settings=settings,
        backend=backend,
        task_store=task_store,
        asset_store=asset_store,
        providers=providers,
        styles=StyleRegistry(STYLES_DIR),
    )
    runner.run_sync(owner_id, task_id)
    runner.shutdown()

    final = task_store.get(owner_id, task_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    artworks: list[dict] = []
    for item in final.artworks:
        target = out_dir / f"{task_id}_a{item.attempt}.png"
        target.write_bytes(asset_store.get(item.path))
        artworks.append(
            {
                "attempt": item.attempt,
                "score": item.score,
                "passed": item.passed,
                "issues": item.issues,
                "path": str(target),
            }
        )
    best = max(artworks, key=lambda a: (bool(a["passed"]), a["score"] or 0)) if artworks else None
    return {
        "task_id": task_id,
        "state": final.state.value,
        "inspect": hints.model_dump(),
        "quality": final.quality.model_dump(),
        "attempts": final.attempts.model_dump(),
        "upstream_calls": final.upstream_calls,
        "artworks": artworks,
        "best": best,
    }


def _side_by_side(results: list[dict], out_path: Path) -> None:
    """左=旧稿、右=新稿，下面一行指标。"""
    font = ImageFont.load_default()
    pad, gutter, caption_h = 10, 8, 26
    tiles: list[list[Image.Image]] = []
    for item in results:
        cells = []
        for path in (item.get("old_artwork"), (item.get("best") or {}).get("path")):
            p = Path(path) if path else None
            if p is not None and p.exists():
                with Image.open(p) as img:
                    img = img.convert("RGB")
                    cells.append(img.resize((round(img.width * THUMB_H / img.height), THUMB_H)))
            else:
                cells.append(Image.new("RGB", (THUMB_H, THUMB_H), (235, 235, 235)))
        tiles.append(cells)

    widths = [max(tile[i].width for tile in tiles) for i in (0, 1)]
    width = pad * 2 + sum(widths) + gutter
    height = pad * 2 + len(tiles) * (THUMB_H + caption_h + gutter)
    sheet = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)
    y = pad
    for item, cells in zip(results, tiles):
        x = pad
        for i, cell in enumerate(cells):
            sheet.paste(cell, (x, y))
            x += widths[i] + gutter
        checks = (item.get("quality") or {}).get("checks") or {}
        draw.text(
            (pad, y + THUMB_H + 4),
            f"[{item['index']:02d}] {item['name']}  |  新稿质检 {item['quality'].get('score')}  "
            f"|  生成 {item['attempts']['used_in_round']} 次  |  实色块 {checks.get('thick_ink_share')}  "
            f"|  轮廓 {checks.get('shoe_silhouette_match')}  |  {item['state']}",
            fill=(20, 20, 20),
            font=font,
        )
        y += THUMB_H + caption_h + gutter
    sheet.save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="用当前规则重画一批鞋并对比")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="", help="只跑这些序号（对应数据集里的编号），逗号分隔")
    parser.add_argument("--style", default="", help="风格 id（默认用 .env 的 STYLE_ID，例如 watercolor）")
    args = parser.parse_args()

    dataset = Path(args.dataset).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    wanted = {int(x) for x in args.only.split(",") if x.strip()}

    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    items = [i for i in manifest["items"] if not wanted or i["index"] in wanted]
    print(f"要重画 {len(items)} 张；风格 = {args.style or "(默认)"}\n")

    results: list[dict] = []
    tmp_root = Path(tempfile.mkdtemp(prefix="shoe-eval-"))
    try:
        for item in items:
            folder = dataset / "items" / item["folder"]
            name = (item["meta"]["inspect"] or {}).get("display_name") or folder.name
            print(f"[{item['index']:02d}] {name} …", end=" ", flush=True)
            result = regenerate(
                folder / "source_0.png",
                data_dir=tmp_root / item["folder"],
                out_dir=out / "artworks",
                style_id=args.style,
            )
            result.update(
                index=item["index"],
                folder=item["folder"],
                name=name,
                old_artwork=str(folder / "artwork_a1.png"),
            )
            results.append(result)
            checks = (result["quality"] or {}).get("checks") or {}
            print(
                f"{result['state']}｜质检 {result['quality'].get('score')}｜"
                f"生成 {result['attempts']['used_in_round']} 次｜"
                f"轮廓 {checks.get('shoe_silhouette_match')}｜实色块 {checks.get('thick_ink_share')}"
            )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    (out / "regenerate.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _side_by_side(results, out / "before-after.png")
    print(f"\n完成 → {out}")
    print("  明细    regenerate.json")
    print("  对比图  before-after.png（左=旧稿，右=新稿）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
