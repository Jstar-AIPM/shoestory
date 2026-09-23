# V2 上传图冒烟报告（真实模型端到端：体检 → 生成 → 质检 → 归档）

> 生成时间：2026-09-23T14:27:39+08:00
> 结论：**通过**
> 输入图：本机实测用的球鞋商品页截图（不入仓库）（1260x2736，199 KB）

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
| 体检·CV 定位（本机计算） | 2.05 | {"tier": "multi", "subject": {"status": "multi", "count": 3}} |
| 体检·AI 识别（本机计算） | 9.44 | {"tier": "ok", "display_name": "Jordan Air Jordan 36", "logo": "无限符号（∞）", "texts": []} |
| 建任务（上传图） | 1.11 | {"state": "preprocessing", "archive_name": "Jordan Air Jordan 36"} |
| 取画稿并自检 | 0.12 | {"canvas_score": 1.0} |

- 状态轨迹：preprocessing → generating → verifying → awaiting_effect_confirm
- 最终状态：awaiting_effect_confirm
- 归档标题（体检识别）：Jordan Air Jordan 36
- 上游调用次数：2｜上游调用：
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
  "message": "认出来了：Jordan Air Jordan 36。",
  "detail": {
    "brand": "Jordan",
    "model_name": "Air Jordan 36",
    "colorway": "",
    "display_name": "Jordan Air Jordan 36",
    "logo_type": "无限符号（∞）",
    "logo_position": "鞋身后跟侧面白色饰片上",
    "logo_fill_required": false,
    "texts": [],
    "text_stamps": [],
    "shoe_count": 1,
    "confidence": 0.98
  },
  "subject": {
    "status": "ok",
    "count": 1
  },
  "crop": [
    343,
    988,
    771,
    449
  ]
}
```

## 质检结果

```json
{
  "score": 0.899,
  "attempts": 1,
  "checks": {
    "shoe_silhouette_match": 0.82,
    "logo_legibility": 1.0,
    "style_consistency": 0.86,
    "noise_level": 0.9,
    "canvas_ratio": 1.0,
    "logo_filled": 1.0,
    "laces_solid_ratio": 0.05,
    "text_legible": 1.0
  },
  "issues": [
    "原图未见品牌标识，logo_legibility 与 logo_filled 不参与判定",
    "外底边缘出现成排短排线，属于风格规则中禁止的排线表达",
    "参考图仅展示鞋身局部，完整鞋头与中底形态无法充分核对，鞋型相似度按可见部分判断",
    "后跟装饰性无限符号被实心填黑，面积较小但与原图细线标识表现不完全一致"
  ],
  "verdict": "pass",
  "best_attempt": 1,
  "artwork_check": {
    "width": 1536,
    "height": 1024,
    "ratio": "1536:1024",
    "ratio_ok": true,
    "binary": true,
    "white_ratio": 0.948,
    "background": "white",
    "background_ok": true,
    "canvas_score": 1.0,
    "has_text_overlay": false,
    "style_metrics": {
      "ink_ratio": 0.052,
      "filled_block_share": 0.0,
      "mean_stroke_px": 3.42,
      "solid_black_share": 0.0495,
      "dot_count": 40,
      "hatch_suspect": 4,
      "components": 181,
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
  "white_ratio": 0.948,
  "background": "white",
  "background_ok": true,
  "canvas_score": 1.0,
  "has_text_overlay": false
}
```

画稿：人工确认三件事 —— 鞋型像不像 / Logo 是否实心 / 鞋带有没有被涂成黑块。

## 诚实性声明

- 本报告由脚本自动生成，未经人工改写；`conclusion=待验` 表示**没有**执行真实调用。
- mock 结果不会写成本报告的“通过”。
