#!/usr/bin/env python
"""从风格参考图里量化出目标区间（把“像不像”变成可验证的数字）。

用法（在 backend/ 目录下）：
    python scripts/style_calibrate.py                 # 默认读 ../风格参考
    python scripts/style_calibrate.py --dir <目录>

输出：控制台表格 + docs/风格量化指标.md（可直接抄进 bw_lineart.yaml 的 style_metrics）
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.cv.imageio import to_rgb_on_white  # noqa: E402
from app.services.cv.style import measure_style  # noqa: E402

METRIC_KEYS = ["ink_ratio", "mean_stroke_px", "solid_black_share", "dot_count", "hatch_suspect"]


def main() -> int:
    parser = argparse.ArgumentParser(description="量化风格参考图")
    parser.add_argument("--dir", default=str(REPO_ROOT / "风格参考"))
    parser.add_argument("--size", default="1536x1024", help="先归一到这个画布再度量（与产出对齐）")
    args = parser.parse_args()

    paths = sorted(
        p for p in glob.glob(str(Path(args.dir) / "*")) if Path(p).suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not paths:
        print(f"没有找到参考图：{args.dir}")
        return 1

    target_w, target_h = (int(v) for v in args.size.lower().split("x"))
    rows: list[dict] = []
    for path in paths:
        from io import BytesIO

        from PIL import Image

        image = to_rgb_on_white(Path(path).read_bytes()).resize((target_w, target_h), Image.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        metrics = measure_style(buffer.getvalue())
        metrics["name"] = Path(path).name
        rows.append(metrics)

    # 目标区间：取参考图的 min/max，并留 20% 余量（避免过拟合到某一张）
    targets: dict[str, tuple[float, float]] = {}
    print(f"{'参考图':<32}{'墨量':>8}{'线宽':>8}{'黑块':>8}{'圆点':>7}{'细线':>7}")
    print("-" * 72)
    for row in rows:
        print(
            f"{row['name'][:30]:<32}{row['ink_ratio']:>8.4f}{row['mean_stroke_px']:>8.2f}"
            f"{row['solid_black_share']:>8.4f}{row['dot_count']:>7}{row['hatch_suspect']:>7}"
        )
    print("-" * 72)
    for key in ("ink_ratio", "mean_stroke_px", "solid_black_share"):
        values = [r[key] for r in rows]
        low, high = min(values), max(values)
        margin = max((high - low) * 0.25, high * 0.15)
        targets[key] = (round(max(0.0, low - margin), 4), round(high + margin, 4))
    dot_counts = [r["dot_count"] for r in rows]
    targets["dot_count"] = (0, int(max(dot_counts) * 1.6) + 10)
    hatch = [r["hatch_suspect"] for r in rows]
    targets["hatch_suspect"] = (0, int(max(hatch) * 2.0) + 10)

    print("建议写入 bw_lineart.yaml 的 style_metrics（含余量）：")
    for key, (low, high) in targets.items():
        print(f"  {key}: [{low}, {high}]")
    print("\n参考图内部一致性（越小越稳定）：")
    for key in METRIC_KEYS:
        values = [r[key] for r in rows]
        if len(values) > 1 and statistics.mean(values):
            spread = statistics.pstdev(values) / (statistics.mean(values) or 1)
            print(f"  {key}: 相对波动 {spread:.1%}")

    out = REPO_ROOT / "docs" / "风格量化指标.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 风格参考图的量化指标（用于约束与验收）",
        "",
        f"> 参考图目录：`{args.dir}`｜度量前统一归一到 {args.size}",
        "",
        "| 参考图 | 墨量占比 | 平均线宽(px) | 实心黑块占比 | 小圆点数 | 疑似排线细线数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['ink_ratio']:.4f} | {row['mean_stroke_px']:.2f} | "
            f"{row['solid_black_share']:.4f} | {row['dot_count']} | {row['hatch_suspect']} |"
        )
    lines += ["", "## 目标区间（含余量，可直接抄进 `bw_lineart.yaml`）", "", "```yaml", "style_metrics:"]
    for key, (low, high) in targets.items():
        lines.append(f"  {key}: [{low}, {high}]")
    lines += ["```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
