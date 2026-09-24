"""轻量去背景 + GrabCut 精修（阶段 1 不引入 rembg，见风险 #3）。

## 为什么需要"精修"这一步（2026-09-24 补）

原来的抠图只有一条规则：**与画面边框颜色的距离 > 40 就算主体**。
它在"深色鞋 + 浅背景"上很好用，但遇到**白鞋 + 白底**时会犯一个致命错误：
**鞋子自己白色的部分（白色鞋面、白色中底）与背景色几乎一样，被当成背景删掉了。**

实测证据（2026-09-24 线上任务）：
- Nike PG 4：掩膜只剩黑勾、红饰片这些彩色零件，**白色鞋面全丢**（覆盖率 0.135）。
  骨架图因此没有鞋头的轮廓，模型只能自己编 —— 生成结果是一个楔形。
- Jordan Carmelo 1.5：白色中底整块消失。

修法：拿粗掩膜当"可能是主体"的初始值，交给 OpenCV 自带的 **GrabCut** 精修。
它同时用颜色模型和边界梯度，能把"与背景同色但被轮廓围住的白色区域"补回来。
实测 PG4 覆盖率 0.135 → 0.271，轮廓完整贴合整只鞋；耗时百毫秒级，仍是本机计算、不花钱。

失败不致命：任何异常都回退为原图（`method=fallback_original`），
由后续"白底归一 + 二值化"兜底，绝不因为抠图失败而中断链路。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgba

MIN_KEEP_RATIO = 0.05  # 主体至少占画面 5%，否则判定抠图失败并回退
BORDER_COLOR_TOLERANCE = 40
GRABCUT_ITERATIONS = 3  # 实测 3 次已经够稳；加到 5 只增加耗时、结果几乎一致
BORDER_BAND_RATIO = 0.02  # 边框留一条"确定是背景"的窄带，喂给 GrabCut
#: 精修至少要"多留下"这么多像素，否则认为没收益、保留粗掩膜。
#: 0.005 是实测出来的：Carmelo 1.5 的白中底只多占 1.9% 画面，闸门设 2% 会把它整块判成"无收益"。
MIN_REFINE_GAIN = 0.005
#: 精修后若覆盖超过这个比例，说明 GrabCut 失控（把整张图都当主体了），回退
MAX_REFINE_RATIO = 0.85
#: 矩形初始化时从四边内缩的比例（给 GrabCut 一点"确定是背景"的余地）
RECT_INSET_RATIO = 0.03
#: 矩形初始化后，若掩膜包围盒几乎等于矩形，说明它只是照抄了矩形、没真找到主体
RECT_TAKEN_RATIO = 0.97


def _largest_component(mask: np.ndarray) -> np.ndarray:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if num <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = int(np.argmax(areas)) + 1
    return np.where(labels == best, 255, 0).astype(np.uint8)


def _close_gaps(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """把外轮廓内部的空洞填满（GrabCut 偶尔会把鞋面内部判成背景）。"""
    height, width = mask.shape[:2]
    flood = mask.copy()
    canvas = np.zeros((height + 2, width + 2), np.uint8)
    cv2.floodFill(flood, canvas, (0, 0), 255)
    return mask | cv2.bitwise_not(flood)


def _coarse_mask(rgb: np.ndarray) -> np.ndarray:
    """原来的启发式：与边框颜色距离 > 40。快，但对白鞋会漏掉白色部分。"""
    height, _width = rgb.shape[:2]
    border = np.concatenate(
        [
            rgb[0:3, :, :].reshape(-1, 3),
            rgb[-3:, :, :].reshape(-1, 3),
            rgb[:, 0:3, :].reshape(-1, 3),
            rgb[:, -3:, :].reshape(-1, 3),
        ]
    )
    background = np.median(border, axis=0)
    distance = np.linalg.norm(rgb.astype(np.float32) - background.astype(np.float32), axis=2)
    mask = (distance > BORDER_COLOR_TOLERANCE).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return _largest_component(mask)


def _init_grabcut(rgb: np.ndarray, coarse: np.ndarray) -> np.ndarray:
    """构造 GrabCut 的初始标记。

    边框那条"确定是背景"的窄带只在**粗掩膜没有碰到那一侧**时才标 ——
    否则遇到"主体被裁到贴边"的图，会把鞋子边缘当成背景切掉。
    """
    height, width = rgb.shape[:2]
    band = max(3, int(min(height, width) * BORDER_BAND_RATIO))
    marks = np.full((height, width), cv2.GC_PR_BGD, np.uint8)
    # 种子稍微膨胀一圈：让 GrabCut 从"确定是鞋"的地方往外长，
    # 更容易把紧贴轮廓、与背景同色的白色区域一起收进来（实测 PG4 覆盖率 0.205 → 0.27）。
    seed = cv2.dilate(coarse, np.ones((5, 5), np.uint8), iterations=1)
    marks[seed > 0] = cv2.GC_PR_FGD
    if not coarse[:band, :].any():
        marks[:band, :] = cv2.GC_BGD
    if not coarse[-band:, :].any():
        marks[-band:, :] = cv2.GC_BGD
    if not coarse[:, :band].any():
        marks[:, :band] = cv2.GC_BGD
    if not coarse[:, -band:].any():
        marks[:, -band:] = cv2.GC_BGD
    return marks


def _refine_mask(rgb: np.ndarray, coarse: np.ndarray) -> np.ndarray | None:
    """以粗掩膜为种子的 GrabCut 精修。返回 None 表示"没收益或失控"，调用方保留粗掩膜。"""
    marks = _init_grabcut(rgb, coarse)
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(
        rgb, marks, None, background_model, foreground_model, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_MASK
    )
    mask = np.isin(marks, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype(np.uint8) * 255
    mask = _fill_holes(_largest_component(_close_gaps(mask)))

    coarse_ratio = float((coarse > 0).mean())
    ratio = float((mask > 0).mean())
    if ratio > MAX_REFINE_RATIO or ratio - coarse_ratio < MIN_REFINE_GAIN:
        return None
    return mask


def _refine_from_rect(rgb: np.ndarray) -> np.ndarray | None:
    """退路：粗掩膜小到不可用时，用"内缩一圈的矩形"做 GrabCut 初始化（经典用法）。

    为什么需要它（2026-09-24 自测发现）：粗掩膜太小的典型原因就是"鞋子几乎全白"——
    而那正是最需要 GrabCut 的场景。原来的逻辑会在这时直接回退到原图（连抠图都不做），
    等于在最该修的地方放弃。现在改成：先用矩形初始化救一次，真救不回来再回退。
    """
    height, width = rgb.shape[:2]
    inset = max(2, int(min(height, width) * RECT_INSET_RATIO))
    rect = (inset, inset, width - 2 * inset, height - 2 * inset)
    if rect[2] <= 0 or rect[3] <= 0:  # pragma: no cover - 图太小
        return None
    marks = np.zeros((height, width), np.uint8)
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(
        rgb, marks, rect, background_model, foreground_model, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_RECT
    )
    mask = np.isin(marks, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype(np.uint8) * 255
    mask = _fill_holes(_largest_component(_close_gaps(mask)))
    if float((mask > 0).mean()) > MAX_REFINE_RATIO:
        return None
    # 矩形初始化有一个危险：画面里根本没有主体时，GrabCut 会把整个矩形当成主体（凭空造一个）。
    # 判别方法很直接：它只是把矩形照抄了一遍 —— 那样掩膜的包围盒会几乎等于矩形。
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:  # pragma: no cover - 防御
        return None
    box_w, box_h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if box_w >= rect[2] * RECT_TAKEN_RATIO and box_h >= rect[3] * RECT_TAKEN_RATIO:
        return None
    return mask


def segment_shoe(data: bytes) -> tuple[bytes, dict]:
    """返回 (PNG 字节, 元信息)。已有透明通道时直接透传。"""
    img = to_rgba(data)
    alpha = np.array(img.split()[-1])
    if alpha.min() < 250:
        return encode_png(img), {"method": "alpha_passthrough"}

    try:
        rgb = np.array(img.convert("RGB"))
        coarse = _coarse_mask(rgb)
        coarse_ratio = float((coarse > 0).mean())

        mask: np.ndarray | None = None
        meta: dict = {}
        try:
            if coarse_ratio < MIN_KEEP_RATIO:
                # 粗掩膜小到不可用 —— 典型就是"鞋子几乎全白"。别急着放弃，先让 GrabCut 试一次。
                mask = _refine_from_rect(rgb)
            else:
                mask = _refine_mask(rgb, coarse)
        except cv2.error:  # pragma: no cover - GrabCut 内部异常不致命
            mask = None

        if mask is not None and float((mask > 0).mean()) < MIN_KEEP_RATIO:
            # 精修结果也小得不像主体（实测：一张纯白图里只有一个 3x3 噪点时，
            # 矩形初始化会把那颗噪点当成主体选出来）—— 当作没找到主体
            mask = None

        if mask is not None:
            meta = {
                "method": "grabcut_rect" if coarse_ratio < MIN_KEEP_RATIO else "border_color_threshold+grabcut",
                "keep_ratio": round(float((mask > 0).mean()), 4),
                "coarse_keep_ratio": round(coarse_ratio, 4),
                "refine_gain": round(float((mask > 0).mean()) - coarse_ratio, 4),
            }
        elif coarse_ratio >= MIN_KEEP_RATIO:
            mask = coarse
            meta = {"method": "border_color_threshold", "keep_ratio": round(coarse_ratio, 4)}
        else:
            # 连 GrabCut 都救不回来（主体不足画面 5%）—— 回退原图，由后续白底归一兜底
            return encode_png(img), {"method": "fallback_original", "reason": "subject_too_small"}

        out = img.copy()
        out.putalpha(Image.fromarray(mask))
        return encode_png(out), meta
    except Exception as exc:  # pragma: no cover - 防御性回退
        return encode_png(img), {"method": "fallback_original", "reason": type(exc).__name__}
