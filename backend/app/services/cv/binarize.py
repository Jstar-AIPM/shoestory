"""二值化与画稿硬指标检查（确定性代码，不信模型）。

`refine_lineart`：自适应/Otsu 二值化 -> 去小噪点 -> 保证像素只有 0/255。
`check_artwork`：3:2 比例、纯二值、白底占比 —— 画稿是否合格由代码判定。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.cv.imageio import encode_png, to_rgb_on_white
MIN_WHITE_RATIO = 0.60
MIN_COMPONENT_AREA = 8  # 小于 8 像素的连通域视为噪点
RATIO_TOLERANCE = 0.01
#: 彩色画稿的"纸色"必须够浅（亮度），否则整张糊满颜色也会被判成"背景"
MIN_PAPER_LUMINANCE = 200.0


def refine_lineart(
    data: bytes,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    padding_ratio: float = 0.03,
) -> tuple[bytes, dict]:
    """二值化 + 去噪，**并归一到固定的 3:2 白底画布**。

    为什么必须做这一步：不同上游/不同版本返回的尺寸不一样（例如 Seedream 5.0 pro
    指定分辨率档位时由模型决定最终像素），而 PRD 要求画稿固定 3:2、白底、纯二值。
    这里做“等比缩放 + 白底居中补齐”，保证不管模型返回什么尺寸，硬指标恒成立。
    白底补边对“白底黑线”的画稿是视觉无损的。
    """
    gray = np.array(to_rgb_on_white(data).convert("L"))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    ink = (binary == 0).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    removed = 0
    if num > 1:
        for label in range(1, num):
            if stats[label, cv2.CC_STAT_AREA] < MIN_COMPONENT_AREA:
                ink[labels == label] = 0
                removed += 1

    out = np.where(ink > 0, 0, 255).astype(np.uint8)
    resized = False
    if target_width and target_height and (out.shape[1], out.shape[0]) != (target_width, target_height):
        out = _fit_into_canvas(out, target_width, target_height, padding_ratio)
        resized = True

    meta = {
        "components_removed": removed,
        "white_ratio": round(float((out > 127).mean()), 4),
        "binary": bool(np.all((np.unique(out) == 0) | (np.unique(out) == 255))),
        "normalized_to_canvas": resized,
        "output_size": f"{out.shape[1]}x{out.shape[0]}",
    }
    return encode_png(Image.fromarray(out, mode="L")), meta


def _fit_into_canvas(
    binary: np.ndarray, target_width: int, target_height: int, padding_ratio: float
) -> np.ndarray:
    """等比缩放主体居中放入目标画布，四周补白（并进行一次重二值化）。"""
    source = Image.fromarray(binary, mode="L")
    inner_w = max(1, int(target_width * (1 - 2 * padding_ratio)))
    inner_h = max(1, int(target_height * (1 - 2 * padding_ratio)))
    scale = min(inner_w / source.width, inner_h / source.height)
    new_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    resized = source.resize(new_size, Image.LANCZOS)

    canvas = Image.new("L", (target_width, target_height), 255)
    canvas.paste(resized, ((target_width - new_size[0]) // 2, (target_height - new_size[1]) // 2))

    # 缩放会引入灰阶，重新二值化一次，保证输出只有 0/255
    arr = np.array(canvas)
    _, again = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return again.astype(np.uint8)


def parse_hex_color(value: str, fallback: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    """把 `#rrggbb` / `rrggbb` 解析成 RGB；非法就返回 fallback。"""
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return fallback


def fit_colored_artwork(
    data: bytes,
    *,
    target_width: int,
    target_height: int,
    padding_ratio: float = 0.03,
    background: str = "#ffffff",
) -> tuple[bytes, dict]:
    """彩色画稿（水彩等）的规范化：**只做等比缩放 + 补边**，绝不二值化。

    为什么单独一个函数（2026-09-24）：`refine_lineart` 的核心是 Otsu 二值化 + 强制 0/255，
    那是黑白线稿风格的要求；用在彩色画稿上会把颜色直接抹平。
    硬指标仍然保持一致：尺寸固定、3:2、居中、四周留白。
    """
    img = to_rgb_on_white(data)
    inner_w = max(1, int(target_width * (1 - 2 * padding_ratio)))
    inner_h = max(1, int(target_height * (1 - 2 * padding_ratio)))
    scale = min(inner_w / img.width, inner_h / img.height)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    resized = img.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), parse_hex_color(background))
    canvas.paste(resized, ((target_width - new_size[0]) // 2, (target_height - new_size[1]) // 2))
    meta = {
        "normalized_to_canvas": True,
        "binarized": False,
        "background": background,
        "output_size": f"{target_width}x{target_height}",
        "scale": round(scale, 4),
    }
    return encode_png(canvas), meta


def check_artwork(
    data: bytes,
    expected_width: int,
    expected_height: int,
    *,
    require_binary: bool = True,
    min_background_ratio: float = MIN_WHITE_RATIO,
    background_label: str = "white",
) -> dict:
    """画稿硬指标：比例 3:2、纯二值、白底。canvas_ratio 分数由此判定。

    ``require_binary``（2026-09-24 新增）：**不是所有风格都是二值的**。
    彩色风格（水彩）要求"纯二值"等于把正确产出判为不合格 —— 而且它真的会把颜色捣掉。
    所以按风格切换：
    - 黑白线稿：要求纯二值 + 白底（原行为）
    - 彩色风格：只要求比例正确 + 背景色淡且留白够（背景色由画风决定，不是纯白）
    """
    rgb = np.array(to_rgb_on_white(data).convert("RGB"))
    gray = np.array(to_rgb_on_white(data).convert("L"))
    height, width = gray.shape[:2]
    unique = np.unique(gray)
    binary = bool(np.all((unique == 0) | (unique == 255)))
    expected_ratio = expected_width / expected_height
    ratio = width / height if height else 0.0
    ratio_ok = abs(ratio - expected_ratio) <= RATIO_TOLERANCE
    size_ok = (width, height) == (expected_width, expected_height)

    if require_binary:
        background_ratio = float((gray > 127).mean())
        paper_luminance = 255.0  # 纯白底，无需单独判亮度
    else:
        # 背景"是纸色而不是主体"：以边框的中位色为基准，算主体之外有多少
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
        background_ratio = float((distance <= 25).mean())
        # ⚠️ 光有"占比"不够：一张整片糊满颜色的图，它的边框中位色就是它自己，
        # 占比会是 1.0 而"通过"。所以还要要求背景是**浅色**（纸色），
        # 这同时对应风格约定里的"暖白/米白水彩纸"。
        paper_luminance = float(0.299 * paper[0] + 0.587 * paper[1] + 0.114 * paper[2])

    background_ok = background_ratio >= min_background_ratio
    if not require_binary and paper_luminance < MIN_PAPER_LUMINANCE:
        # ⚠️ 光有"占比"不够：一张整片糊满颜色的图，它的边框中位色就是它自己，
        # 占比会是 1.0 而"通过"。所以还要要求背景是**浅色**（纸色）——
        # 这同时对应风格约定里的"暖白 / 米白水彩纸"。
        background_ok = False
    return {
        "width": width,
        "height": height,
        "ratio": f"{width}:{height}",
        "ratio_ok": bool(ratio_ok and size_ok),
        "binary": binary,
        "require_binary": require_binary,
        "white_ratio": round(float((gray > 127).mean()), 4),
        "background_ratio": round(background_ratio, 4),
        "paper_luminance": round(paper_luminance, 1),
        "background": background_label if background_ok else "other",
        "background_ok": bool(background_ok),
        "canvas_score": 1.0
        if (ratio_ok and size_ok and background_ok and (binary or not require_binary))
        else 0.0,
        # 本项目 overlay_text=none，从不叠加文字；目视为验收项 8.6
        "has_text_overlay": False,
    }
