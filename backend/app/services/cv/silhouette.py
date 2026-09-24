"""轮廓一致性度量（确定性代码，不靠模型打分）。

## 为什么需要它

2026-09-24 产品反馈里最重的一条是「PG4 的鞋身轮廓都没有完全还原」。查下来根因很清楚：
那张图是**白鞋配白底**，`edge_map`（Canny 60/160）抓不到浅灰鞋面与白底之间的边界，
于是骨架图上**鞋头那段轮廓根本不存在**，模型只能自己编 —— 编成了一个楔形。

但系统里其实**一直存着精确的轮廓**：`segment_shoe` 抠出来的 alpha 掩膜就是鞋的边界。
只是没人拿它去校验产出。这个模块把"轮廓像不像"从"让视觉模型看一眼"变成可计算的数字：

- `iou`           外形重合度（各自按 bbox 归一化后比对，只比形状、不比位置大小）
- `bands`         把画面按宽度切三段（鞋头 / 中段 / 后跟）分别算重合度
                  → 专治"鞋头被画没了"这类**局部塌陷**（整体 IoU 会被后跟的平均掉）
- `aspect_delta`  长宽比偏差 → 抓"被压扁/被拉长"
- `fill_ratio`    画稿外轮廓填满面积 / 原鞋掩膜面积 → 抓"只画了一半"

## 两个输入的来源

- **原鞋掩膜**：优先用 `cutout.png` 的 alpha（抠图结果，最准）；
  没有就退回从 `canvas_3x2.png` 按"非白像素"估。
- **画稿轮廓**：画稿是白底黑线，取墨迹的外轮廓并填充
  （用外轮廓而不是"填洞"，这样即使线条有断口也能得到完整外形）。
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import to_rgb_on_white

#: 归一化后的比对尺寸。太小会丢形状细节，太大对评测没增益还拖慢批量跑
NORM_W = 512
NORM_H = 256

#: 把画面按宽度切成几段（鞋头 / 中段 / 后跟）
BANDS = 3

#: 两个来源的留白比例（分别来自风格模板 canvas.padding 与 refine_lineart 的默认值）。
#: 比对轮廓时要先按它们把两个坐标系对齐，否则会有 12% 的系统性缩放差。
SUBJECT_PAD = 0.08
ARTWORK_PAD = 0.03

#: 比对用的标准画布尺寸（与 `.env` 的 ARTWORK_WIDTH/HEIGHT 一致）
CANVAS_W = 1536
CANVAS_H = 1024

#: 画布上"非白"的判定阈值。白鞋面在画布上约 200–245（保留了原始浅灰），
#: 所以不能用 250 这种一刀切，否则会把白鞋也算进背景
CANVAS_INK_THRESHOLD = 248


def _largest_component(mask: np.ndarray) -> np.ndarray:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if num <= 1:
        return mask
    best = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    return labels == best


def subject_mask_from_cutout(cutout_png: bytes) -> np.ndarray | None:
    """从抠图结果的 alpha 通道取原鞋掩膜（最准的来源）。"""
    with Image.open(io.BytesIO(cutout_png)) as img:
        if img.mode not in ("RGBA", "LA"):
            return None
        alpha = np.array(img.split()[-1])
    mask = alpha > 8
    if mask.sum() == 0:
        return None
    return _largest_component(mask)


def subject_mask_from_canvas(canvas_png: bytes) -> np.ndarray:
    """退路：从 3:2 白底画布按"非白像素"估掩膜。"""
    gray = np.array(to_rgb_on_white(canvas_png).convert("L"))
    mask = gray < CANVAS_INK_THRESHOLD
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return _largest_component(mask)


def subject_mask_on_canvas(
    cutout_png: bytes,
    *,
    width: int = CANVAS_W,
    height: int = CANVAS_H,
    padding_ratio: float = SUBJECT_PAD,
) -> np.ndarray | None:
    """把抠图掩膜按 ``normalize_view`` **同一套变换**映射到 3:2 画布坐标系。

    为什么必须映射而不能直接比：抠图是原图尺寸（例如 705x429），画稿是 1536x1024。
    直接把两者各自缩到同一个尺寸，会把长宽比拉坏，位置也对不上 —— 自测时踩过这个坑
    （那样算出来的 IoU 全是 0.15–0.8 的噪声，分不出好坏）。

    这个函数就是 `cv/normalize.py: normalize_to_canvas` 的掩膜版：同样的
    bbox 裁切 → 等比缩放 → 居中贴到二维画布。两边参数一致才能对上。
    """
    mask = subject_mask_from_cutout(cutout_png)
    if mask is None:
        return None
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    cropped = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]

    inner_w = max(1, int(width * (1 - 2 * padding_ratio)))
    inner_h = max(1, int(height * (1 - 2 * padding_ratio)))
    scale = min(inner_w / cropped.shape[1], inner_h / cropped.shape[0])
    new_w = max(1, int(cropped.shape[1] * scale))
    new_h = max(1, int(cropped.shape[0] * scale))
    resized = cv2.resize(
        cropped.astype(np.uint8), (new_w, new_h), interpolation=cv2.INTER_NEAREST
    ) > 0

    canvas = np.zeros((height, width), bool)
    ox, oy = (width - new_w) // 2, (height - new_h) // 2
    canvas[oy : oy + new_h, ox : ox + new_w] = resized
    return canvas


def artwork_silhouette(artwork_png: bytes, *, from_background: bool = False, tolerance: int = 26) -> np.ndarray:
    """画稿的外形。

    两种取法，按风格选：

    - ``from_background=False``（黑白线稿）：取墨迹（灰度 < 128）的外轮廓并整块填充。
    - ``from_background=True``（**彩色画稿**）：取"与纸色不同"的区域。

    ⚠️ 为什么彩色必须换一种取法（2026-09-24 实测）：水彩画稿里**没有黑墨**，
    拿“灰度 < 128”去找，得到的是零碎几块 —— 轮廓重合度直接掉到 0.03–0.67，
    于是每张水彩都被误判“轮廓塔陷”并白白重画一次。
    """
    if from_background:
        rgb = np.array(to_rgb_on_white(artwork_png).convert("RGB"))
        border = np.concatenate(
            [
                rgb[0:3, :, :].reshape(-1, 3),
                rgb[-3:, :, :].reshape(-1, 3),
                rgb[:, 0:3, :].reshape(-1, 3),
                rgb[:, -3:, :].reshape(-1, 3),
            ]
        )
        paper = np.median(border, axis=0)
        distance = np.linalg.norm(rgb.astype(np.float32) - paper.astype(np.float32), axis=2)
        mask = (distance > tolerance).astype(np.uint8) * 255
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = _largest_component(mask > 0).astype(np.uint8) * 255
        # 填洞：水彩内部可能有与纸色接近的浅色区域，不填会被当成背景
        flood = mask.copy()
        canvas = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8)
        cv2.floodFill(flood, canvas, (0, 0), 255)
        return (mask | cv2.bitwise_not(flood)) > 0

    gray = np.array(to_rgb_on_white(artwork_png).convert("L"))
    ink = (gray < 128).astype(np.uint8) * 255
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(ink)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled > 0


def _normalized(mask: np.ndarray, *, width: int = NORM_W, height: int = NORM_H) -> tuple[np.ndarray, float] | None:
    """按自身 bbox 裁出来再缩放到统一尺寸 —— 只比形状，不受位置/大小影响。

    另外把**原始长宽比**一并返回：统一尺寸后两张图都是 512x256，
    再拿缩放后的尺寸算长宽比就永远相等（这是第一版的 bug），
    所以必须在缩放前算。
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    cropped = mask[box[1] : box[3], box[0] : box[2]]
    aspect = cropped.shape[1] / max(1, cropped.shape[0])
    resized = cv2.resize(
        cropped.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST
    )
    return resized > 0, float(aspect)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 0.0
    return float(np.logical_and(a, b).sum()) / float(union)


def _fit_box_frame(mask: np.ndarray, pad: float) -> np.ndarray:
    """把掩膜换到「内框坐标系」：两个来源的留白比例不同（画布 8% / 画稿 3%），
    直接比会因为缩放差 12% 而系统性偏低；除以 (1-2*pad) 就对齐了。

    依然保留**位置与大小**信息 —— 这正是 bbox 归一化会丢掉的东西。
    """
    height, width = mask.shape[:2]
    scale = 1.0 / max(1e-6, (1 - 2 * pad))
    resized = cv2.resize(
        mask.astype(np.uint8),
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_NEAREST,
    )
    return cv2.resize(resized, (NORM_W * 2, NORM_H * 2), interpolation=cv2.INTER_NEAREST) > 0


def silhouette_metrics(
    subject: np.ndarray,
    artwork: np.ndarray,
    *,
    bands: int = BANDS,
    subject_pad: float = SUBJECT_PAD,
    artwork_pad: float = ARTWORK_PAD,
) -> dict:
    """比对两副掩膜，返回可判定的数字。"""
    a_norm = _normalized(subject)
    b_norm = _normalized(artwork)
    if a_norm is None or b_norm is None:
        return {"ok": False, "reason": "empty_mask"}
    a, subject_aspect = a_norm
    b, artwork_aspect = b_norm

    band_iou: list[float] = []
    for index in range(bands):
        x0 = index * NORM_W // bands
        x1 = (index + 1) * NORM_W // bands
        band_iou.append(round(_iou(a[:, x0:x1], b[:, x0:x1]), 4))

    # 分段覆盖率用**内框坐标系**算：bbox 归一化会把"鞋头整块省略"拉伸回去（自测就踩过），
    # 而内框坐标系保留位置与大小，那块地方没东西就是没东西。
    a_frame = _fit_box_frame(subject, subject_pad)
    b_frame = _fit_box_frame(artwork, artwork_pad)
    frame_width = a_frame.shape[1]
    band_iou_frame: list[float] = []
    for index in range(bands):
        x0 = index * frame_width // bands
        x1 = (index + 1) * frame_width // bands
        band_iou_frame.append(round(_iou(a_frame[:, x0:x1], b_frame[:, x0:x1]), 4))

    return {
        "ok": True,
        "iou": round(_iou(a, b), 4),
        "iou_frame": round(_iou(a_frame, b_frame), 4),
        "band_iou": band_iou,
        "band_iou_frame": band_iou_frame,
        "worst_band": int(np.argmin(band_iou_frame)),
        "worst_band_iou": min(band_iou_frame),
        "aspect_delta": round(abs(artwork_aspect - subject_aspect), 3),
        "subject_aspect": round(subject_aspect, 3),
        "artwork_aspect": round(artwork_aspect, 3),
        "fill_ratio": round(float(b.sum()) / max(1.0, float(a.sum())), 4),
    }


def compare_silhouette(
    *,
    cutout_png: bytes | None,
    canvas_png: bytes,
    artwork_png: bytes,
    bands: int = BANDS,
    canvas_size: tuple[int, int] = (CANVAS_W, CANVAS_H),
    canvas_padding: float = SUBJECT_PAD,
    artwork_padding: float = ARTWORK_PAD,
    from_background: bool = False,
) -> dict:
    """便捷入口：直接喂三个文件（cutout 可以为 None，会自动退回画布估掩膜）。

    ``from_background=True`` 用于彩色风格（水彩）—— 它的画稿里没有黑墨，
    必须用“与纸色不同”取主体，否则指标完全失效（详见 `artwork_silhouette`）。
    """
    subject = (
        subject_mask_on_canvas(
            cutout_png, width=canvas_size[0], height=canvas_size[1], padding_ratio=canvas_padding
        )
        if cutout_png
        else None
    )
    if subject is None:
        subject = subject_mask_from_canvas(canvas_png)
    metrics = silhouette_metrics(
        subject,
        artwork_silhouette(artwork_png, from_background=from_background),
        bands=bands,
        subject_pad=canvas_padding,
        artwork_pad=artwork_padding,
    )
    labels = ["toe", "mid", "heel"][:bands]  # 画稿规定鞋头朝左
    if metrics.get("ok"):
        metrics["band_labels"] = labels
        metrics["band_iou_named"] = dict(zip(labels, metrics["band_iou_frame"]))
        metrics["missing_bands"] = [
            name for name, value in metrics["band_iou_named"].items() if value < 0.6
        ]
    return metrics
