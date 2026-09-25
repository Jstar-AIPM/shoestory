#!/usr/bin/env python
"""风格一致性探针：**不需要照片**，直接“型号 → 黑白线稿”，看不同鞋款风格是否统一。

为什么需要它（PM 的判断）：不管用户是拍照片还是只输型号，我们都已经知道这是哪款鞋；
验证风格一致性不必依赖用户照片。这个脚本用同一套提示词与风格模板，对多款鞋各出一张，
然后用确定性指标（参考图量化得出）横向对比。

用法（在 backend/ 目录下）：
    python scripts/style_probe.py
    python scripts/style_probe.py --models "Nike KD 12" "ASICS GEL-NIMBUS 27" "Air Jordan 14"

产出：
    docs/风格探针/〈型号〉.png          每款一张线稿
    docs/风格探针/montage.png           横向拼图（一眼看风格是否统一）
    docs/screenshots/                    指标对比表 + 结论
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.core.container import build_container  # noqa: E402
from app.services.cv.binarize import check_artwork, refine_lineart  # noqa: E402
from app.services.cv.style import compare_to_targets, measure_style  # noqa: E402
from app.services.providers.base import CallRecorder  # noqa: E402
from app.services.style.loader import PromptSpec  # noqa: E402

DEFAULT_MODELS = ["ASICS GEL-NIMBUS 27", "Nike KD 12", "Air Jordan 14"]
THUMB = (512, 341)


def build_prompt(style, model_name: str, with_reference: bool):
    if with_reference:
        return style
    note = (
        "\n【本次没有参考照片】请依据你对这款鞋的了解，画出它的正侧面线稿，"
        "鞋型结构必须符合该型号的真实特征；不要把具体配色画成彩色，只输出黑白线稿。"
    )
    return style.model_copy(
        update={"prompt": PromptSpec(positive=style.prompt.positive + note, negative=style.prompt.negative)}
    )


def montage(images: list[tuple[str, bytes]]) -> bytes:
    label_h = 46
    width = THUMB[0] * len(images) + 20 * (len(images) + 1)
    height = THUMB[1] + label_h + 40
    sheet = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    x = 20
    for name, data in images:
        thumb = Image.open(io.BytesIO(data)).convert("RGB").resize(THUMB, Image.LANCZOS)
        sheet.paste(thumb, (x, 20))
        draw.rectangle([x, 20 + THUMB[1], x + THUMB[0], 20 + THUMB[1] + label_h], fill=(255, 255, 255))
        draw.text((x + 12, 20 + THUMB[1] + 16), name, fill=(0, 0, 0))
        x += THUMB[0] + 20
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="风格一致性探针（型号直出）")
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="不重新生成，只对 docs/风格探针/ 下已有图片重算指标（不产生费用）",
    )
    args = parser.parse_args()

    settings = Settings()
    container = build_container(settings)
    if container.providers.mode != "real":
        print("⚠️  当前是演示模式（未配置真实模型），探针需要真实模型。请先填好 .env。")
        return 2

    style = container.styles.get(settings.style_id)
    targets = {
        key: (float(values[0]), float(values[1]))
        for key, values in (style.quality_gate.style_metrics or {}).items()
        if isinstance(values, (list, tuple)) and len(values) == 2
    }

    out_dir = REPO_ROOT / "docs" / "风格探针"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    images: list[tuple[str, bytes]] = []

    if args.reuse:
        for path in sorted(out_dir.glob("*.png")):
            if path.name == "montage.png":
                continue
            final = path.read_bytes()
            metrics = measure_style(final)
            ok, issues = compare_to_targets(metrics, targets)
            check = check_artwork(final, settings.artwork_width, settings.artwork_height)
            images.append((path.stem, final))
            rows.append(
                {
                    "name": path.stem,
                    "seconds": None,
                    "ink_ratio": metrics["ink_ratio"],
                    "solid_black_share": metrics["solid_black_share"],
                    "dot_count": metrics["dot_count"],
                    "hatch_suspect": metrics["hatch_suspect"],
                    "mean_stroke_px": metrics["mean_stroke_px"],
                    "style_ok": ok,
                    "style_issues": issues,
                    "canvas_score": check["canvas_score"],
                    "cost": 0.0,
                }
            )
            print(
                f"· {path.stem}: 墨量 {metrics['ink_ratio']:.4f} 黑块 {metrics['solid_black_share']:.4f} "
                f"圆点 {metrics['dot_count']} 排线 {metrics['hatch_suspect']} "
                f"-> {'闸门通过 ✓' if ok else '；'.join(issues)}"
            )

    for model_name in ([] if args.reuse else args.models):
        recorder = CallRecorder(settings.task_max_upstream_calls, settings)
        prompt_style = build_prompt(style, model_name, with_reference=False)
        started = time.perf_counter()
        try:
            raw = container.providers.generator.generate(
                canvas_png=None,
                style=prompt_style,
                attempt=1,
                recorder=recorder,
                model_name=model_name,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {model_name} 生成失败：{type(exc).__name__}: {exc}")
            rows.append({"name": model_name, "error": f"{type(exc).__name__}"})
            continue
        elapsed = time.perf_counter() - started

        final, refine_meta = refine_lineart(
            raw, target_width=settings.artwork_width, target_height=settings.artwork_height
        )
        metrics = measure_style(final)
        ok, issues = compare_to_targets(metrics, targets)
        check = check_artwork(final, settings.artwork_width, settings.artwork_height)
        (out_dir / f"{model_name}.png").write_bytes(final)
        images.append((model_name, final))
        rows.append(
            {
                "name": model_name,
                "seconds": round(elapsed, 1),
                "ink_ratio": metrics["ink_ratio"],
                "solid_black_share": metrics["solid_black_share"],
                "dot_count": metrics["dot_count"],
                "hatch_suspect": metrics["hatch_suspect"],
                "mean_stroke_px": metrics["mean_stroke_px"],
                "style_ok": ok,
                "style_issues": issues,
                "canvas_score": check["canvas_score"],
                "cost": recorder.total_cost,
            }
        )
        print(
            f"✓ {model_name}: 墨量 {metrics['ink_ratio']:.4f} 黑块 {metrics['solid_black_share']:.4f} "
            f"圆点 {metrics['dot_count']} 排线 {metrics['hatch_suspect']} "
            f"-> {'风格一致 ✓' if ok else '偏离：' + '；'.join(issues)}  ({elapsed:.0f}s)"
        )

    if images:
        (out_dir / "montage.png").write_bytes(montage(images))

    lines = [
        "# 风格一致性探针（型号直出，无参考照片）",
        "",
        "> 用**同一套**风格提示词与约束，对不同鞋款各生成一张，横向对比风格是否统一。",
        "> 指标区间来自 4 张风格参考图的实测量化（`bw_lineart.yaml 的 style_metrics 注释`）。",
        "",
        "| 型号 | 墨量占比 | 实心黑块占比 | 小圆点 | 疑似排线 | 平均线宽 | 画布硬指标 | 风格一致 | 耗时(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if "error" in row:
            lines.append(f"| {row['name']} | 生成失败：{row['error']} | | | | | | ✗ | |")
            continue
        lines.append(
            f"| {row['name']} | {row['ink_ratio']:.4f} | {row['solid_black_share']:.4f} | "
            f"{row['dot_count']} | {row['hatch_suspect']} | {row['mean_stroke_px']:.2f} | "
            f"{row['canvas_score']} | {'✓' if row['style_ok'] else '✗'} | {row['seconds']} |"
        )
    consistent = [r for r in rows if r.get("style_ok")]
    lines += [
        "",
        f"**结论**：{len(consistent)}/{len([r for r in rows if 'error' not in r])} 款落在参考图的风格区间内。",
        "",
        "目标区间：",
        "",
        "```yaml",
        *[f"{key}: [{low}, {high}]" for key, (low, high) in targets.items()],
        "```",
        "",
        "拼图：`docs/风格探针/montage.png`（请人工目视确认风格是否统一）。",
        "",
    ]
    report = REPO_ROOT / "docs" / "风格探针.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告：{report}")
    print(f"拼图：{out_dir / 'montage.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
