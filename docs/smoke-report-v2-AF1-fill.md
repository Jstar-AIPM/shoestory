# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）

> 生成时间：2026-09-24T20:56:31+08:00
> 结论：**通过**
> 输入图：`../·质量评测/dataset/items/10__tk_20260923T142751_5595/source_0.png`（987x516，252 KB）

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
| 体检·CV 定位（本机计算） | 0.17 | {"tier": "ok", "subject": {"status": "ok", "count": 1}} |
| 体检·AI 识别 | 14.17 | {"tier": "ok", "display_name": "Nike Air Force 1", "logo": "耐克勾形", "texts": ["AIR"]} |
| 建任务（上传图） | 0.08 | {"state": "preprocessing", "archive_name": "Nike Air Force 1"} |
| 取画稿并自检 | 0.05 | {"canvas_score": 1.0} |

- 状态轨迹：preprocessing → generating → verifying → awaiting_effect_confirm
- 最终状态：awaiting_effect_confirm
- 归档标题（体检识别）：Nike Air Force 1
- 上游调用次数：2
- 生成次数（含自动重试）：1｜是否**首次即达标**：True

## V2 特有自检（坐标约定与动效素材）

| 检查项 | 结果 | 含义 |
| --- | --- | --- |
| 坐标系一致（EXIF 摆正 + 缩图换算） | ✅ | /inspect 报的尺寸 987x516 必须等于摆正后的真实尺寸 987x516；不一致 = 会静默裁错位置 |
| CV 草稿可用（生成动效） | ✅ | `draft.png` 应返回 200 + image/png |

## 体检结论（第③步 AI 识别的原文）

```json
{
  "tier": "ok",
  "message": "认出来了：Nike Air Force 1。",
  "detail": {
    "brand": "Nike",
    "model_name": "Air Force 1",
    "colorway": "小麦色",
    "display_name": "Nike Air Force 1",
    "logo_type": "耐克勾形",
    "logo_position": "鞋身两侧",
    "logo_visibility": "full",
    "logo_fill_required": true,
    "texts": [
      "AIR"
    ],
    "text_stamps": [
      {
        "text": "AIR",
        "position": "中底后跟处",
        "box": [
          0.768,
          0.736,
          0.824,
          0.806
        ]
      }
    ],
    "shoe_count": 1,
    "confidence": 0.99
  },
  "subject": {
    "status": "ok",
    "count": 1
  },
  "crop": [
    1,
    1,
    986,
    515
  ]
}
```

## 质检结果

```json
{
  "score": 0.9585,
  "attempts": 1,
  "checks": {
    "shoe_silhouette_match": 0.96,
    "logo_legibility": 0.97,
    "style_consistency": 0.92,
    "noise_level": 0.96,
    "canvas_ratio": 1.0,
    "logo_filled": 1.0,
    "laces_solid_ratio": 0.0,
    "text_legible": 0.95
  },
  "issues": [
    "外底前掌与后跟的颗粒齿纹被大幅简化，未完全保留原鞋外底纹理",
    "部分缝线以细碎点线表现，短横虚线的连续性略弱"
  ],
  "verdict": "pass",
  "best_attempt": 1,
  "artwork_check": {
    "width": 1536,
    "height": 1024,
    "ratio": "1536:1024",
    "ratio_ok": true,
    "binary": true,
    "white_ratio": 0.9298,
    "background": "white",
    "background_ok": true,
    "canvas_score": 1.0,
    "has_text_overlay": false,
    "style_metrics": {
      "ink_ratio": 0.0702,
      "filled_block_share": 0.0223,
      "mean_stroke_px": 14.35,
      "solid_black_share": 0.0669,
      "thick_ink_share": 0.02348,
      "max_stroke_px": 111.1,
      "dot_count": 118,
      "hatch_suspect": 1,
      "components": 227,
      "size": "1536x1024"
    },
    "style_ok": true,
    "silhouette": {
      "ok": true,
      "iou": 0.963,
      "iou_frame": 0.9586,
      "band_iou": [
        0.9565,
        0.9941,
        0.933
      ],
      "band_iou_frame": [
        0.9272,
        0.9824,
        0.9422
      ],
      "worst_band": 0,
      "worst_band_iou": 0.9272,
      "aspect_delta": 0.002,
      "subject_aspect": 1.997,
      "artwork_aspect": 1.995,
      "fill_ratio": 1.0131,
      "band_labels": [
        "toe",
        "mid",
        "heel"
      ],
      "band_iou_named": {
        "toe": 0.9272,
        "mid": 0.9824,
        "heel": 0.9422
      },
      "missing_bands": []
    }
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
  "white_ratio": 0.9298,
  "background": "white",
  "background_ok": true,
  "canvas_score": 1.0,
  "has_text_overlay": false
}
```

画稿文件：`docs/smoke-artifacts/tk_20260924T205601_4f66.png`（请人工确认三件事：鞋型像不像 / Logo 是否**实心** / 鞋带有没有被涂成黑块）

## 诚实性声明

- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。
- mock 结果不会写成本报告的“通过”。
