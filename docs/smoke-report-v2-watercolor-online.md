# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）

> 生成时间：2026-09-25T08:38:22+08:00
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
| 体检·CV 定位（本机计算） | 0.36 | {"tier": "ok", "subject": {"status": "ok", "count": 1}} |
| 体检·AI 识别 | 3.41 | {"tier": "ok", "display_name": "Nike PG 4", "logo": "耐克勾形", "texts": []} |
| 建任务（上传图） | 0.87 | {"state": "preprocessing", "archive_name": "Nike PG 4"} |
| 取画稿并自检 | 0.63 | {"canvas_score": 1.0, "style": "watercolor"} |

- 状态轨迹：preprocessing → generating → refining → verifying → generating → refining → verifying → awaiting_effect_confirm
- 最终状态：awaiting_effect_confirm
- 归档标题（体检识别）：Nike PG 4
- 上游调用次数：4
- 生成次数（含自动重试）：2｜是否**首次即达标**：False

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
    "colorway": "",
    "display_name": "Nike PG 4",
    "logo_type": "耐克勾形",
    "logo_position": "鞋身两侧",
    "logo_visibility": "full",
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
  "score": 0.959,
  "attempts": 2,
  "checks": {
    "shoe_silhouette_match": 0.96,
    "logo_legibility": 0.97,
    "style_consistency": 0.94,
    "noise_level": 0.96,
    "canvas_ratio": 1.0,
    "logo_filled": 1.0,
    "laces_solid_ratio": 0.0,
    "text_legible": 0.2,
    "silhouette_iou": 0.6855
  },
  "issues": [
    "中底黑色饰片内的细小标识被画成难以辨认的抽象笔触",
    "鞋身局部深色边缘略重，但未形成整鞋粗黑勾线",
    "风格一致性未达标：轮廓重合度 0.6855 低于下限 0.7（缺失部位：toe）"
  ],
  "verdict": "pass",
  "best_attempt": 2,
  "artwork_check": {
    "width": 1536,
    "height": 1024,
    "ratio": "1536:1024",
    "ratio_ok": true,
    "binary": false,
    "require_binary": false,
    "white_ratio": 0.8941,
    "background_ratio": 0.7895,
    "paper_luminance": 246.5,
    "background": "paper",
    "background_ok": true,
    "canvas_score": 1.0,
    "has_text_overlay": false,
    "style_metrics": {
      "subject_ratio": 0.3234,
      "canvas_size": "1536x1024",
      "paper_luminance": 246.5,
      "chromatic_ratio": 0.1763,
      "source_chromatic_ratio": 0.2867,
      "hue_match": 0.3759,
      "sat_ratio": 1.065,
      "source_saturation": 136.5,
      "artwork_saturation": 145.4
    },
    "style_ok": true,
    "silhouette": {
      "ok": true,
      "iou": 0.5797,
      "iou_frame": 0.6855,
      "band_iou": [
        0.3656,
        0.5589,
        0.7513
      ],
      "band_iou_frame": [
        0.3949,
        0.6926,
        0.8527
      ],
      "worst_band": 0,
      "worst_band_iou": 0.3949,
      "aspect_delta": 0.047,
      "subject_aspect": 1.72,
      "artwork_aspect": 1.673,
      "fill_ratio": 1.2149,
      "band_labels": [
        "toe",
        "mid",
        "heel"
      ],
      "band_iou_named": {
        "toe": 0.3949,
        "mid": 0.6926,
        "heel": 0.8527
      },
      "missing_bands": [
        "toe"
      ]
    }
  },
  "note": "这张的线条风格没完全达到标准，您可以先收下，或再画一次。"
}
```

## 画稿硬指标（确定性代码判定）

```json
{
  "width": 1536,
  "height": 1024,
  "ratio": "1536:1024",
  "ratio_ok": true,
  "binary": false,
  "require_binary": false,
  "white_ratio": 0.8941,
  "background_ratio": 0.7895,
  "paper_luminance": 246.5,
  "background": "paper",
  "background_ok": true,
  "canvas_score": 1.0,
  "has_text_overlay": false
}
```

画稿文件：`docs/smoke-artifacts/tk_20260925T083708_da45.png`（请人工确认三件事：鞋型像不像 / Logo 是否**实心** / 鞋带有没有被涂成黑块）

## 诚实性声明

- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。
- mock 结果不会写成本报告的“通过”。
