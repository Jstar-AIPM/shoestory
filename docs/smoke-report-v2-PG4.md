# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）

> 生成时间：2026-09-24T20:42:41+08:00
> 结论：**通过**
> 输入图：`../·质量评测/dataset/items/24__tk_20260923T213636_a224/source_0.png`（705x429，213 KB）

## 环境与模型

| 项 | 值 |
| --- | --- |
| Provider 模式 | real |
| 视觉模型（体检 / 质检） | doubao-seed-2-1-pro-260915 |
| 图生图模型 | doubao-seedream-5-0-pro-260628 |
| Python | 3.12.3 |

## 链路与耗时

| 步骤 | 耗时（秒） | 备注 |
| --- | --- | --- |
| 体检·CV 定位（本机计算） | 0.05 | {"tier": "ok", "subject": {"status": "ok", "count": 1}} |
| 体检·AI 识别 | 3.64 | {"tier": "ok", "display_name": "Nike PG 4", "logo": "耐克勾形", "texts": []} |
| 建任务（上传图） | 0.05 | {"state": "preprocessing", "archive_name": "Nike PG 4"} |
| 取画稿并自检 | 0.03 | {"canvas_score": 1.0} |

- 状态轨迹：preprocessing → generating → verifying → awaiting_effect_confirm
- 最终状态：awaiting_effect_confirm
- 归档标题（体检识别）：Nike PG 4
- 上游调用次数：2
- 生成次数（含自动重试）：1｜是否**首次即达标**：True

## V2 特有自检（坐标约定与动效素材）

| 检查项 | 结果 | 含义 |
| --- | --- | --- |
| 坐标系一致（EXIF 摆正 + 缩图换算） | ✅ | /inspect 报的尺寸 705x429 必须等于摆正后的真实尺寸 705x429；不一致 = 会静默裁错位置 |
| CV 草稿可用（生成动效） | ✅ | `draft.png` 应返回 200 + image/png |

## 体检结论（第③步 AI 识别的原文）

```json
{
  "tier": "ok",
  "message": "认出来了：Nike PG 4。",
  "detail": {
    "brand": "Nike",
    "model_name": "PG 4",
    "colorway": "白红藏青",
    "display_name": "Nike PG 4",
    "logo_type": "耐克勾形",
    "logo_position": "鞋身外侧中部",
    "logo_fill_required": true,
    "texts": [],
    "text_stamps": [],
    "shoe_count": 1,
    "confidence": 0.99
  },
  "subject": {
    "status": "ok",
    "count": 1
  },
  "crop": [
    0,
    0,
    705,
    429
  ]
}
```

## 质检结果

```json
{
  "score": 0.935,
  "attempts": 1,
  "checks": {
    "shoe_silhouette_match": 0.92,
    "logo_legibility": 0.96,
    "style_consistency": 0.9,
    "noise_level": 0.93,
    "canvas_ratio": 1.0,
    "logo_filled": 1.0,
    "laces_solid_ratio": 0.0,
    "text_legible": 1.0
  },
  "issues": [
    "中底表面绘制了较多散点，虽数量不多但原鞋泼墨纹理按抽象化要求可进一步省略"
  ],
  "verdict": "pass",
  "best_attempt": 1,
  "artwork_check": {
    "width": 1536,
    "height": 1024,
    "ratio": "1536:1024",
    "ratio_ok": true,
    "binary": true,
    "white_ratio": 0.9472,
    "background": "white",
    "background_ok": true,
    "canvas_score": 1.0,
    "has_text_overlay": false,
    "style_metrics": {
      "ink_ratio": 0.0528,
      "filled_block_share": 0.0164,
      "mean_stroke_px": 12.02,
      "solid_black_share": 0.0514,
      "thick_ink_share": 0.01736,
      "max_stroke_px": 96.3,
      "dot_count": 115,
      "hatch_suspect": 0,
      "components": 164,
      "size": "1536x1024"
    },
    "style_ok": false
  },
  "note": ""
}
```

## 画稿硬指标（确定性代码判定）

```json
{
  "width": 1536,
  "height": 1024,
  "ratio": "1536:1024",
  "ratio_ok": true,
  "binary": true,
  "white_ratio": 0.9472,
  "background": "white",
  "background_ok": true,
  "canvas_score": 1.0,
  "has_text_overlay": false
}
```

画稿文件：`docs/smoke-artifacts/tk_20260924T204207_a803.png`（请人工确认三件事：鞋型像不像 / Logo 是否**实心** / 鞋带有没有被涂成黑块）

## 诚实性声明

- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。
- mock 结果不会写成本报告的“通过”。
