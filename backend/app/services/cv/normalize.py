"""归一化到 3:2 白底标准画布：主体居中、等比例缩放、四周 8% 留白。

鞋头朝向本阶段无法可靠判定：保留原方向并在元信息里记录 `direction_verified=False`
（PRD 要求鞋头朝左；阶段 1 由生成模型与提示词负责，阶段 2 再考虑镜像校正）。
"""

from __future__ import annotations

from PIL import Image

from app.services.cv.imageio import encode_png, to_rgba


def normalize_to_canvas(
    data: bytes,
    *,
    width: int,
    height: int,
    padding_ratio: float = 0.08,
) -> tuple[bytes, dict]:
    img = to_rgba(data)
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        bbox = (0, 0, img.width, img.height)
    subject = img.crop(bbox)

    inner_w = max(1, int(width * (1 - 2 * padding_ratio)))
    inner_h = max(1, int(height * (1 - 2 * padding_ratio)))
    scale = min(inner_w / subject.width, inner_h / subject.height)
    new_size = (max(1, int(subject.width * scale)), max(1, int(subject.height * scale)))
    subject = subject.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    offset = ((width - new_size[0]) // 2, (height - new_size[1]) // 2)
    canvas.paste(subject, offset, mask=subject.split()[-1])

    meta = {
        "width": width,
        "height": height,
        "padding": f"{int(padding_ratio * 100)}%",
        "subject_bbox": list(bbox),
        "direction_verified": False,
    }
    return encode_png(canvas), meta
