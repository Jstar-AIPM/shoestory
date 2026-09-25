"""清晰度评估（确定性）—— 只用来"建议换一张"，**不拦人**。

## 为什么做这个（2026-09-25 产品反馈）

原来上传入口有一条硬规则：**图片短边 < 400px 直接拒收**。实测很伤人：
用户从手机截图里裁出一块（506×320），画面是清楚的，却根本传不上去、
界面上也没有任何反应 —— 他既不知道限制是多少，也不知道该怎么办。

而我们的画法是水彩抽象，本来就不需要照片级细节。所以：
- **尺寸不再作为门槛**（只留一个 64px 的技术底线，防的是"这压根不是图片"）；
- 改成看**清晰度**：真的糊了才提示"换一张会更清楚"，而且**仍然允许继续画**。

## 指标：Laplacian 方差（归一化后）

先等比缩放到长边 800 再算 —— **这一步不能省**：Laplacian 方差随分辨率下降，
不做归一化的话，小尺寸但清楚的照片会被误判成"糊"（而这正是原来那条规则的毛病）。

实测标定（2026-09-25）：

| 图 | 分数 |
| --- | --- |
| 用户从截图裁出的小图（506×320） | 56.6 |
| 用户自己挑的两张标准示例（商品图） | 31.3 / 67.0 |
| 线上真图（大尺寸商品图） | 300–520 |
| 人为轻度模糊（k=1） | 13.8 |
| 人为中度模糊（k=3） | 3.5 |

所以门槛取 **10**：只拦"明显糊了"（k≥3 那一档），正常商品图和小图都在 30 以上，
留了三倍余量。**它是个粗筛，不是精细判断** —— 所以只提示、不阻断。
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

#: 归一化用的长边。选 800 是因为与"画布长边 1536 的一半"接近，
#: 既能反映放大到画布后的观感，又不至于把小图放大出一堆插值噪声
NORMALIZE_EDGE = 800

#: 低于它就认为"明显模糊"。标定依据见文件头，正常图在 30 以上
BLUR_FLOOR = 10.0


def sharpness_score(data: bytes) -> float:
    """清晰度分数（越大越清楚）。无法解码时返回 0。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            gray = np.array(img.convert("L"))
    except Exception:  # noqa: BLE001 - 解不开就当作"无法评估"，由上层另行处理
        return 0.0
    if gray.size == 0:
        return 0.0
    # **无论大小都要归一化**（放大也要）。
    # 我第一版写了"只缩小、不放大"，结果小图不归一化 —— 实测就是漏的：
    # 一张 506×320 的糊图在原尺寸下算出来仍高于门槛，提示根本不触发，
    # 而它放大到画布（1536）后明明很糊。归一化才是这个指标可比的前提。
    scale = NORMALIZE_EDGE / max(gray.shape[:2])
    gray = cv2.resize(
        gray,
        (max(1, round(gray.shape[1] * scale)), max(1, round(gray.shape[0] * scale))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4,
    )
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def is_too_blurry(data: bytes, *, floor: float = BLUR_FLOOR) -> bool:
    return sharpness_score(data) < floor
