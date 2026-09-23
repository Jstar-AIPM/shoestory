# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）

> 生成时间：2026-09-23T12:50:33+08:00
> 结论：**通过**
> 输入图：本机实测用的球鞋商品页截图（不入仓库）（1260x2736，140 KB）

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
| 体检·CV 定位（本机计算） | 1.44 | {"tier": "ok", "subject": {"status": "ok", "count": 1}} |
| 体检·AI 识别 | 5.57 | {"tier": "ok", "display_name": "Nike PG 1", "logo": "耐克勾形", "texts": []} |
| 建任务（上传图） | 1.16 | {"state": "preprocessing", "archive_name": "Nike PG 1"} |
| 取画稿并自检 | 0.14 | {"canvas_score": 1.0} |
| 归档 | 0.61 | {"shoe_id": "sh_20260923T125032_bf2e", "model_name": null} |

- 状态轨迹：preprocessing → generating → refining → verifying → awaiting_effect_confirm
- 最终状态：awaiting_effect_confirm
- 归档标题（体检识别）：Nike PG 1
- 上游调用次数：2
- 生成次数（含自动重试）：1｜是否**首次即达标**：True

## V2 特有自检（坐标约定与动效素材）

| 检查项 | 结果 | 含义 |
| --- | --- | --- |
| 坐标系一致（EXIF 摆正 + 缩图换算） | ✅ | /inspect 报的尺寸 1260x2736 必须等于摆正后的真实尺寸 1260x2736；不一致 = 会静默裁错位置 |
| CV 草稿可用（生成动效） | ✅ | `draft.png` 应返回 200 + image/png |

## 体检结论（第③步 AI 识别的原文）

```json
{
  "tier": "ok",
  "message": "认出来了：Nike PG 1。",
  "detail": {
    "brand": "Nike",
    "model_name": "PG 1",
    "colorway": "",
    "display_name": "Nike PG 1",
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
    38,
    1029,
    1199,
    599
  ]
}
```

## 质检结果

```json
{
  "score": 0.9325,
  "attempts": 1,
  "checks": {
    "shoe_silhouette_match": 0.92,
    "logo_legibility": 0.95,
    "style_consistency": 0.9,
    "noise_level": 0.93,
    "canvas_ratio": 1.0,
    "logo_filled": 1.0,
    "laces_solid_ratio": 0.0,
    "text_legible": 0.0
  },
  "issues": [
    "前掌绑带上的黄色小饰条被画成了空心轮廓，未按原鞋小色块保留",
    "鞋舌与领口造型较原鞋略有简化"
  ],
  "verdict": "pass",
  "best_attempt": 1,
  "artwork_check": {
    "width": 1536,
    "height": 1024,
    "ratio": "1536:1024",
    "ratio_ok": true,
    "binary": true,
    "white_ratio": 0.9395,
    "background": "white",
    "background_ok": true,
    "canvas_score": 1.0,
    "has_text_overlay": false,
    "style_metrics": {
      "ink_ratio": 0.0605,
      "filled_block_share": 0.0149,
      "mean_stroke_px": 10.91,
      "solid_black_share": 0.0591,
      "dot_count": 62,
      "hatch_suspect": 0,
      "components": 86,
      "size": "1536x1024"
    },
    "style_ok": false
  }
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
  "white_ratio": 0.9395,
  "background": "white",
  "background_ok": true,
  "canvas_score": 1.0,
  "has_text_overlay": false
}
```

画稿：人工确认三件事 —— 鞋型像不像 / Logo 是否实心 / 鞋带有没有被涂成黑块。

## 诚实性声明

- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。
- mock 结果不会写成报告的“通过”。
