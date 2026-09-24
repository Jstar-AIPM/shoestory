#!/usr/bin/env python
"""质量评测台：把一批鞋的"画得像不像"变成一张表 + 一张对比图。

## 为什么要有它

改规则（提示词、骨架图、闸门）时必须能回答"这次改动到底变好了没有"。
没有固定的评测集和固定的指标，调参就只能靠感觉 —— 而感觉在这个项目里已经骗过我们两次：

1. `solid_black_share`（面积≥2000 的墨块占比）看起来像"填色够不够"，实测分辨不出好坏：
   被判"太轻"的 AF1 是 0.062，被评"很好"的 PG5 只有 0.041 —— 因为又粗又长的外轮廓
   也被算成了"实心块"。
2. 因此改用 `thick_ink_share`（半径 8px 开运算后剩下的墨量占比，即"宽度超过 16px 的墨块"）
   来量"实色块"，用 `silhouette.iou` 来量"轮廓像不像"。

这个脚本只做一件事：**同一批鞋、同一组确定性指标，改前改后各跑一次，对比**。

## 数据从哪来

`scripts/pull_live_dataset.py` 把线上鞋柜（源图 / 画布 / 骨架 / 每次生成的稿子 / 任务记录）
拉到本地，就是这里的 `--dataset`。

## 用法

    cd backend
    python scripts/quality_eval.py --dataset "../../·质量评测/dataset" --out "../../·质量评测/baseline" \
        --labels "../../·质量评测/labels.json"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.services.cv.silhouette import compare_silhouette  # noqa: E402
from app.services.cv.style import measure_style  # noqa: E402

THUMB_H = 190
PAD = 8
GUTTER = 6
CAPTION_H = 30
COLUMNS = ("source_0.png", "canvas_3x2.png", "edge_map.png", None)  # None = 代表画稿

#: 判定"这双鞋太轻（没有实色块）"的经验下限。
#: 依据 2026-09-24 基线：纯线描的 AJ36 = 0.00000、Melo 5.5 = 0.00055、
#: Stan Smith = 0.00122；被认可的 Carmelo 1.5 = 0.00367、Nike 2024 = 0.02808。
#: 取 0.002 作为分界（这是**当前经验值**，规则改动后要重新标定）。
THICK_INK_FLOOR = 0.0020

#: 判定"轮廓崩了"的下限，用**内框坐标系**的 IoU（保留位置与大小）。
#: 依据 2026-09-24 基线重新标定（见 report.md）。
SILHOUETTE_FLOOR = 0.85


def _artifact_metrics(item_dir: Path, artwork: Path) -> dict:
    art_bytes = artwork.read_bytes()
    row: dict = {f"style_{k}": v for k, v in measure_style(art_bytes).items()}
    canvas = item_dir / "canvas_3x2.png"
    cutout = item_dir / "cutout.png"
    if canvas.exists():
        sil = compare_silhouette(
            cutout_png=cutout.read_bytes() if cutout.exists() else None,
            canvas_png=canvas.read_bytes(),
            artwork_png=art_bytes,
        )
        if sil.get("ok"):
            row["sil_iou"] = sil["iou"]
            row["sil_iou_frame"] = sil["iou_frame"]
            row["sil_toe"] = sil["band_iou_named"]["toe"]
            row["sil_mid"] = sil["band_iou_named"]["mid"]
            row["sil_heel"] = sil["band_iou_named"]["heel"]
            row["sil_missing"] = ",".join(sil["missing_bands"]) or "-"
            row["sil_fill_ratio"] = sil["fill_ratio"]
    return row


def _evaluate_item(item_dir: Path, meta: dict) -> tuple[dict, list[dict]]:
    """返回 (代表产出的指标行, 每一次生成的指标明细)。"""
    artworks = sorted(item_dir.glob("artwork_a*.png"))
    detail: list[dict] = []
    for artwork in artworks:
        attempt = int(artwork.stem.rsplit("a", 1)[-1])
        metrics = _artifact_metrics(item_dir, artwork)
        metrics["attempt"] = attempt
        metrics["file"] = artwork.name
        detail.append(metrics)

    best = (meta.get("quality") or {}).get("best_attempt")
    representative = next((d for d in detail if d["attempt"] == best), None) or (detail[-1] if detail else None)

    row: dict = {
        "task_id": meta.get("task_id"),
        "model": (meta.get("inspect") or {}).get("display_name") or "",
        "logo_type": (meta.get("inspect") or {}).get("logo_type") or "",
        "logo_fill_required": (meta.get("inspect") or {}).get("logo_fill_required"),
        "quality_score": (meta.get("quality") or {}).get("score"),
        "attempts": (meta.get("quality") or {}).get("attempts"),
        "judge_logo_filled": ((meta.get("quality") or {}).get("checks") or {}).get("logo_filled"),
        "artwork": representative["file"] if representative else "",
        "ok": bool(representative),
    }
    if representative:
        row.update({k: v for k, v in representative.items() if k not in ("attempt", "file")})
        # 多次生成之间的抖动 —— 这是"稳定性"的直接证据
        thick = [d.get("style_thick_ink_share") for d in detail if d.get("style_thick_ink_share") is not None]
        iou = [d.get("sil_iou") for d in detail if d.get("sil_iou") is not None]
        row["thick_spread"] = round(max(thick) - min(thick), 5) if len(thick) > 1 else 0.0
        row["iou_spread"] = round(max(iou) - min(iou), 4) if len(iou) > 1 else 0.0
    return row, detail


def _thumb(path: Path, height: int = THUMB_H) -> Image.Image:
    with Image.open(path) as img:
        img = img.convert("RGB")
        scale = height / img.height
        return img.resize((max(1, round(img.width * scale)), height), Image.LANCZOS)


def _build_contact_sheet(rows: list[dict], dataset: Path, out_path: Path) -> None:
    font = ImageFont.load_default()
    tiles: list[list[Image.Image]] = []
    for row in rows:
        item_dir = dataset / "items" / row["_folder"]
        cells: list[Image.Image] = []
        for name in COLUMNS:
            path = item_dir / (row["artwork"] if name is None else name)
            cells.append(
                _thumb(path) if path.exists() else Image.new("RGB", (THUMB_H, THUMB_H), (235, 235, 235))
            )
        tiles.append(cells)

    col_widths = [max(tile[index].width for tile in tiles) for index in range(len(COLUMNS))]
    width = PAD * 2 + sum(col_widths) + GUTTER * (len(COLUMNS) - 1)
    height = PAD * 2 + len(tiles) * (THUMB_H + CAPTION_H + GUTTER)
    sheet = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)

    y = PAD
    for row, tile in zip(rows, tiles):
        x = PAD
        for index, cell in enumerate(tile):
            sheet.paste(cell, (x, y))
            x += col_widths[index] + GUTTER
        caption = (
            f"[{row['_index']:02d}] {row['model'] or '?'} ({row.get('label') or '-'})  "
            f"| judge {row.get('quality_score')}  |  IoU {row.get('sil_iou_frame')} ({row.get('sil_missing')})  "
            f"|  实色块 {row.get('style_thick_ink_share')}  |  最粗 {row.get('style_max_stroke_px')}px  "
            f"|  抖动 {row.get('thick_spread')}"
        )
        draw.text((PAD, y + THUMB_H + 4), caption, fill=(20, 20, 20), font=font)
        y += THUMB_H + CAPTION_H + GUTTER
    sheet.save(out_path)


def _separation_summary(rows: list[dict], metric: str) -> str:
    groups: dict[str, list[float]] = {}
    for row in rows:
        label, value = row.get("label"), row.get(metric)
        if label and isinstance(value, (int, float)):
            groups.setdefault(label, []).append(float(value))
    if len(groups) < 2:
        return ""
    parts = []
    for label in ("good", "fair", "bad"):
        if label in groups:
            values = groups[label]
            parts.append(
                f"{label} n={len(values)} 均值 {sum(values)/len(values):.5f} "
                f"[{min(values):.5f}–{max(values):.5f}]"
            )
    return f"{metric}: " + " | ".join(parts)


SEPARATION_METRICS = (
    "sil_iou",
    "sil_iou_frame",
    "style_thick_ink_share",
    "style_max_stroke_px",
    "style_solid_black_share",
    "style_ink_ratio",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="质量评测台（确定性指标 + 对比图）")
    parser.add_argument("--dataset", required=True, help="pull_live_dataset.py 拉下来的目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--labels", default="", help="人工标注 JSON：{task_id: good|fair|bad}")
    args = parser.parse_args()

    dataset = Path(args.dataset).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    labels: dict[str, str] = {}
    if args.labels:
        labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    rows: list[dict] = []
    details: dict[str, list[dict]] = {}
    for item in manifest["items"]:
        item_dir = dataset / "items" / item["folder"]
        meta = json.loads((item_dir / "meta.json").read_text(encoding="utf-8"))
        row, detail = _evaluate_item(item_dir, meta)
        row["_folder"] = item["folder"]
        row["_index"] = item["index"]
        row["label"] = labels.get(item["task_id"], "")
        rows.append(row)
        details[item["task_id"]] = detail

    columns = [key for key in rows[0] if not key.startswith("_")]
    with (out / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (out / "metrics-detail.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _build_contact_sheet(rows, dataset, out / "contact-sheet.png")

    lines = ["# 质量评测报告", "", f"数据集：`{dataset}`", f"条目：{len(rows)}", ""]
    flagged = [
        row for row in rows
        if row.get("ok") and (
            (row.get("style_thick_ink_share") or 0) < THICK_INK_FLOOR
            or (row.get("sil_iou_frame") or 1) < SILHOUETTE_FLOOR
        )
    ]
    lines += [
        "## 确定性检查会拦下哪些",
        "",
        f"- 实色块下限 `thick_ink_share >= {THICK_INK_FLOOR}`",
        f"- 轮廓下限 `silhouette_iou >= {SILHOUETTE_FLOOR}`",
        f"- 命中：**{len(flagged)} / {len(rows)}**",
        "",
    ]
    for row in flagged:
        reasons = []
        if (row.get("style_thick_ink_share") or 0) < THICK_INK_FLOOR:
            reasons.append(f"太轻({row.get('style_thick_ink_share')})")
        if (row.get("sil_iou_frame") or 1) < SILHOUETTE_FLOOR:
            reasons.append(f"轮廓({row.get('sil_iou_frame')}, 缺{row.get('sil_missing')})")
        lines.append(f"  - `{row['_index']:02d}` {row['model'] or '?'}（{row.get('label') or '未标注'}）："
                     + "、".join(reasons))

    lines += [
        "", "## 指标表", "",
        "| # | 型号 | 标注 | judge分 | IoU内框 | 鞋头 | 中段 | 后跟 | 缺口 | 实色块 | 最粗px | 墨量 | 涂黑 | 排线 | 抖动 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['_index']:02d} | {row['model'] or '?'} | {row.get('label','')} "
            f"| {row.get('quality_score')} | {row.get('sil_iou_frame')} "
            f"| {row.get('sil_toe')} | {row.get('sil_mid')} | {row.get('sil_heel')} "
            f"| {row.get('sil_missing')} | {row.get('style_thick_ink_share')} "
            f"| {row.get('style_max_stroke_px')} | {row.get('style_ink_ratio')} "
            f"| {row.get('style_filled_block_share')} | {row.get('style_hatch_suspect')} "
            f"| {row.get('thick_spread')} |"
        )
    if labels:
        lines += ["", "## 指标分离度（人工标注 vs 指标）", ""]
        for metric in SEPARATION_METRICS:
            summary = _separation_summary(rows, metric)
            if summary:
                lines.append(f"- {summary}")
    lines += ["", "## 对比图", "", "（一行一双：原图 | 画布 | 骨架 | 代表画稿）", "",
              "![contact sheet](contact-sheet.png)", ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"完成 → {out}")
    print(f"  指标表  metrics.csv（{len(rows)} 行）")
    print("  对比图  contact-sheet.png")
    print("  报告    report.md")
    print(f"\n确定性检查命中 {len(flagged)} / {len(rows)}：")
    for row in flagged:
        print(f"  [{row['_index']:02d}] {row['model'] or '?'} ({row.get('label') or '未标注'})  "
              f"实色块={row.get('style_thick_ink_share')}  IoU={row.get('sil_iou_frame')}  缺={row.get('sil_missing')}")
    if labels:
        print("\n指标分离度：")
        for metric in SEPARATION_METRICS:
            summary = _separation_summary(rows, metric)
            if summary:
                print("  " + summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
