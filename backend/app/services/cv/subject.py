"""主体定位：从（可能是 App 截图的）图片里找出"鞋"的候选主体，并给出建议裁切框。

## 为什么需要它（2026-09-22 实测）
用户会用**球鞋 App 商品页的截图**当输入，图里除了鞋还有状态栏、价格、按钮、缩略图。
- 手机截图里详情页的鞋只占图面积约 **5%**，列表页每双约 **1.6%** → **绝对面积不能当判据**；
- 真正能区分"详情页 / 列表页"的是「**候选数量 + 相对大小**」：
  详情页只有 1 个候选；列表页有多个大小相近的候选（实测 5 个 / 2 个）。

## 浅色/白色鞋的坑
白色鞋面与"背景白"很接近，会被判据漏掉，导致框只框住半只鞋（实测发生过）。
因此这里做了两步：
1. 用「高饱和 / 暗区」找到**核心候选**（彩色/深色部分，最稳）；
2. 在核心候选附近用更宽松的「非背景」判据**扩展**到整只鞋（补回白色鞋面与大底）。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: 候选主体的最小面积占比（相对整图）：低于此值视为缩略图/图标噪声
CANDIDATE_MIN_AREA_RATIO = 0.008
#: 像鞋的宽高比区间（侧视图）
SHOE_ASPECT_RATIO = (1.3, 3.2)
#: 建议裁切框的余量（相对主体宽高）
CROP_MARGIN = (0.12, 0.15)
#: 判定"一家独大"的倍数：最大候选 ≥ 次大者该倍数时，认为其余是缩略图/推荐位
DOMINANT_RATIO = 2.0


@dataclass(frozen=True)
class Subject:
    """一个候选主体。"""

    box: tuple[int, int, int, int]  # x, y, w, h
    area: int
    aspect_ratio: float

    @property
    def right(self) -> int:
        return self.box[0] + self.box[2]

    @property
    def bottom(self) -> int:
        return self.box[1] + self.box[3]


def _core_mask(rgb: np.ndarray) -> np.ndarray:
    """核心候选掩码：高饱和度（彩色鞋）或明显偏暗（深色鞋）。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    mask = (((sat > 45) & (val > 25)) | (val < 90)).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))


def _components(mask: np.ndarray) -> list[Subject]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    out: list[Subject] = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i][:5])
        if h <= 0 or w <= 0:
            continue
        out.append(Subject(box=(x, y, w, h), area=area, aspect_ratio=round(w / h, 3)))
    return sorted(out, key=lambda s: -s.area)


def detect_subjects(rgb: np.ndarray, *, min_area_ratio: float = CANDIDATE_MIN_AREA_RATIO) -> list[Subject]:
    """返回"像鞋"的候选主体（按面积从大到小）。"""
    height, width = rgb.shape[:2]
    floor = min_area_ratio * height * width
    low, high = SHOE_ASPECT_RATIO
    return [s for s in _components(_core_mask(rgb)) if s.area >= floor and low <= s.aspect_ratio <= high]


def _background_color(rgb: np.ndarray) -> np.ndarray:
    """用图像四角与边缘取样估计"页面背景色"（商品图多是白底）。"""
    height, width = rgb.shape[:2]
    band = max(4, min(height, width) // 40)
    edges = np.concatenate(
        [
            rgb[:band, :, :].reshape(-1, 3),
            rgb[-band:, :, :].reshape(-1, 3),
            rgb[:, :band, :].reshape(-1, 3),
            rgb[:, -band:, :].reshape(-1, 3),
        ]
    ).astype(np.float32)
    return np.median(edges, axis=0)


def expand_to_full_subject(rgb: np.ndarray, subject: Subject, *, tolerance: float = 8.0) -> Subject:
    """把只框到"彩色/深色部分"的候选，扩展成"整只鞋"。

    实测场景：白色鞋面被判据漏掉，只框住了彩色大底与后跟。
    做法（不再用"固定半径的窗口"，那个半径对小白鞋块会扩不到位）：
    1. 用"离背景色足够远"的宽松判据重建掩码（整图范围）；
    2. 取**包含核心候选中心点**的那个连通域；
    3. 只有当它"确实更大"且宽高比仍像鞋时才采用。
    """
    height, width = rgb.shape[:2]
    background = _background_color(rgb)
    distance = np.linalg.norm(rgb.astype(np.float32) - background, axis=2)
    mask = (distance > tolerance).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    x, y, w, h = subject.box
    cx, cy = min(width - 1, x + w // 2), min(height - 1, y + h // 2)
    label = int(labels[cy, cx])
    if label == 0:
        # 中心点可能落在内部空腔里：在核心框内找面积最大的标签
        region = labels[max(0, y) : y + h, max(0, x) : x + w]
        values, counts = np.unique(region[region > 0], return_counts=True)
        if len(values) == 0:
            return subject
        label = int(values[counts.argmax()])

    bx, by, bw, bh, _area = (int(v) for v in stats[label][:5])
    grown = Subject(box=(bx, by, bw, bh), area=bw * bh, aspect_ratio=round(bw / max(bh, 1), 3))

    low, high = SHOE_ASPECT_RATIO
    bigger = grown.box[2] * grown.box[3] > subject.box[2] * subject.box[3] * 1.05
    if bigger and low <= grown.aspect_ratio <= high:
        return grown
    return subject


def suggest_crop(image_size: tuple[int, int], subject: Subject, *, margin: tuple[float, float] = CROP_MARGIN) -> tuple[int, int, int, int]:
    """给出建议裁切框（含余量，且不超出图片边界）。"""
    width, height = image_size
    x, y, w, h = subject.box
    mx, my = int(w * margin[0]), int(h * margin[1])
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(width, subject.right + mx), min(height, subject.bottom + my)
    return (x0, y0, x1 - x0, y1 - y0)


@dataclass(frozen=True)
class SubjectVerdict:
    """主体判定结果。"""

    status: str  # ok | multi | none
    subjects: list[Subject]
    suggested_crop: tuple[int, int, int, int] | None
    dominant_ratio: float | None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def judge_subjects(rgb: np.ndarray) -> SubjectVerdict:
    """三档判定：ok（单一主体）/ multi（多只相近，疑似列表页）/ none（找不到主体）。

    判定规则来自实测：详情页 → 唯一候选；列表页 → 多个大小相近的候选。
    """
    width, height = rgb.shape[1], rgb.shape[0]
    subjects = detect_subjects(rgb)
    if not subjects:
        return SubjectVerdict(status="none", subjects=[], suggested_crop=None, dominant_ratio=None)

    if len(subjects) == 1:
        picked = expand_to_full_subject(rgb, subjects[0])
        return SubjectVerdict(
            status="ok",
            subjects=[picked],
            suggested_crop=suggest_crop((width, height), picked),
            dominant_ratio=None,
        )

    dominant = subjects[0].area / max(subjects[1].area, 1)
    if dominant >= DOMINANT_RATIO:
        picked = expand_to_full_subject(rgb, subjects[0])
        return SubjectVerdict(
            status="ok",
            subjects=[picked],
            suggested_crop=suggest_crop((width, height), picked),
            dominant_ratio=round(float(dominant), 2),
        )

    return SubjectVerdict(
        status="multi",
        subjects=subjects,
        suggested_crop=suggest_crop((width, height), subjects[0]),
        dominant_ratio=round(float(dominant), 2),
    )
