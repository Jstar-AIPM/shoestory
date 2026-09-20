"""风格度量：把“看起来像不像”变成可比较的数字（确定性代码，不靠模型打分）。

为什么需要它：风格一致性是阶段 1 的核心指标之一，但“线条干净”“不要太乱”这类形容词
无法验证。这里从 4 张参考图里量化出目标区间，之后每张产出都能对照检查。

度量的 5 个指标（都在 1536x1024 归一化画布上计算）：
- ink_ratio        墨量占比：排线/素描会显著推高它
- mean_stroke_px   平均线宽：参考风格是少数几档均匀线宽
- solid_black_share 实心黑块占比：参考风格靠黑块表达明暗
- dot_count        小圆点数量：透气孔用“规律稀疏小点”
- hatch_suspect    疑似排线：细长且宽度 <2.5px 的中小笔画数量
- filled_block_share 大面积涂黑：墨密度 >50% 的区块占画面的比例
  （参考图 3.6%-7.5%；把中底/鞋头整块涂黑的产出会到 13% 以上）
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.cv.imageio import to_rgb_on_white

FILL_BLOCK = 48          # 判定“大面积涂黑”的窗口尺寸
FILL_DENSITY = 0.5       # 窗口内墨密度超过它就算“涂黑块”
DOT_MAX_AREA = 80
BLOCK_MIN_AREA = 2000
HATCH_MIN_AREA = 40
HATCH_MAX_AREA = 900
HATCH_MAX_WIDTH = 2.6
HATCH_MIN_ASPECT = 3.0


def measure_style(image_bytes: bytes) -> dict:
    """返回风格度量字典（纯确定性计算）。"""
    gray = np.array(to_rgb_on_white(image_bytes).convert("L"))
    height, width = gray.shape[:2]
    ink = (gray < 128).astype(np.uint8)
    total = float(width * height) or 1.0

    ink_ratio = float(ink.sum()) / total

    # 平均线宽：对墨迹做距离变换，骨架附近的距离 * 2 ≈ 笔画宽度
    if ink.sum() == 0:
        return {
            "ink_ratio": 0.0,
            "filled_block_share": 0.0,
            "mean_stroke_px": 0.0,
            "solid_black_share": 0.0,
            "dot_count": 0,
            "hatch_suspect": 0,
            "components": 0,
        }
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    skeleton_values = dist[dist > 0]
    mean_stroke = float(np.mean(np.minimum(skeleton_values, 40)) * 2)

    num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
    dot_count = 0
    hatch_suspect = 0
    solid_area = 0
    for label in range(1, num):
        area = int(stats[label, cv2.CC_STAT_AREA])
        box_w = int(stats[label, cv2.CC_STAT_WIDTH])
        box_h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if area >= BLOCK_MIN_AREA:
            solid_area += area
        aspect = max(box_w, box_h) / max(1, min(box_w, box_h))
        if area <= DOT_MAX_AREA and aspect < 1.8:
            dot_count += 1
        elif HATCH_MIN_AREA <= area <= HATCH_MAX_AREA and aspect >= HATCH_MIN_ASPECT:
            # 细长笔画：可能是缝线虚线（正常）也可能是排线（问题）
            # 用笔画宽度再筛一层——排线通常比缝线更细
            component = (_labels == label).astype(np.uint8)
            comp_dist = cv2.distanceTransform(component, cv2.DIST_L2, 3)
            width_est = float(comp_dist.max()) * 2
            if width_est <= HATCH_MAX_WIDTH:
                hatch_suspect += 1

    # 大面积涂黑：滑动窗口里的高密度墨块占比
    height_b = (height // FILL_BLOCK) * FILL_BLOCK
    width_b = (width // FILL_BLOCK) * FILL_BLOCK
    if height_b and width_b:
        blocks = (
            ink[:height_b, :width_b]
            .astype(np.float32)
            .reshape(height_b // FILL_BLOCK, FILL_BLOCK, width_b // FILL_BLOCK, FILL_BLOCK)
            .mean(axis=(1, 3))
        )
        filled_block_share = float((blocks > FILL_DENSITY).mean())
    else:  # pragma: no cover
        filled_block_share = 0.0

    return {
        "ink_ratio": round(ink_ratio, 4),
        "filled_block_share": round(filled_block_share, 4),
        "mean_stroke_px": round(mean_stroke, 2),
        "solid_black_share": round(solid_area / total, 4),
        "dot_count": dot_count,
        "hatch_suspect": hatch_suspect,
        "components": int(num - 1),
        "size": f"{width}x{height}",
    }


def compare_to_targets(metrics: dict, targets: dict) -> tuple[bool, list[str]]:
    """把度量与目标区间比对，返回 (是否在区间内, 偏差说明)。"""
    issues: list[str] = []
    for key, (low, high) in targets.items():
        value = metrics.get(key)
        if value is None:
            continue
        if value < low:
            issues.append(f"{key}={value} 低于参考区间 [{low}, {high}]")
        elif value > high:
            issues.append(f"{key}={value} 高于参考区间 [{low}, {high}]")
    return (not issues), issues
