"""工具：型号 -> 鞋图检索（search_shoe_image）+ 源图下载与校验。

- 空结果 -> IMAGE_SEARCH_EMPTY（**业务结果**，界面提示换写法或走手动源图）
- 下载/读取后一律经 Pillow 真实解码校验（格式/尺寸/大小），拒绝伪装文件
"""

from __future__ import annotations

import httpx

from app.core.errors import AppError, ErrorCode
from app.schemas.task import SourceCandidate
from app.services.cv.imageio import (
    MAX_IMAGE_BYTES,
    encode_png,
    open_image,
    to_rgb_on_white,
    validate_image_bytes,
)
from app.services.providers.base import CallRecorder, ShoeImageSearch

DOWNLOAD_TIMEOUT = 30.0
PREVIEW_MAX_WIDTH = 720


def search_shoe_image(
    model_name: str,
    searcher: ShoeImageSearch,
    limit: int,
    recorder: CallRecorder,
) -> list[SourceCandidate]:
    candidates = searcher.search(model_name=model_name, limit=limit, recorder=recorder)
    candidates = [c for c in candidates if c.url or c.local_path]
    if not candidates:
        raise AppError(ErrorCode.IMAGE_SEARCH_EMPTY, detail={"model_name": model_name})
    return candidates


def _read_local(path: str) -> bytes:
    from pathlib import Path

    file_path = Path(path)
    if not file_path.is_file():
        raise AppError(ErrorCode.SOURCE_NOT_FOUND, detail={"reason": "本地候选图不存在"})
    if file_path.stat().st_size > MAX_IMAGE_BYTES:
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE, detail={"reason": "文件过大"})
    return file_path.read_bytes()


def _download(url: str) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        raise AppError(ErrorCode.UNSUPPORTED_IMAGE, detail={"reason": "仅支持 http(s) 图片地址"})
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise AppError(
                        ErrorCode.SOURCE_NOT_FOUND,
                        message="这张候选图下载失败，请换一张试试。",
                        detail={"status": response.status_code},
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise AppError(
                            ErrorCode.UNSUPPORTED_IMAGE,
                            message="这张图太大了（超过 10MB），请换一张。",
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
    except AppError:
        raise
    except httpx.TimeoutException as exc:
        raise AppError(ErrorCode.UPSTREAM_TIMEOUT, message="下载候选图超时，请重试。") from exc
    except httpx.HTTPError as exc:
        raise AppError(
            ErrorCode.SOURCE_NOT_FOUND, message="下载候选图失败，请换一张试试。"
        ) from exc


def fetch_source_image(candidate: SourceCandidate) -> bytes:
    """取回候选图字节并校验；返回校验通过的图片字节。"""
    if candidate.local_path and not candidate.url:
        data = _read_local(candidate.local_path)
    elif candidate.url:
        data = _download(candidate.url)
    elif candidate.local_path:
        data = _read_local(candidate.local_path)
    else:
        raise AppError(ErrorCode.SOURCE_NOT_FOUND)
    validate_image_bytes(data)
    return data


def fetch_candidate_preview(candidate: SourceCandidate, *, max_width: int = PREVIEW_MAX_WIDTH) -> bytes:
    """做一张缩略预览图给界面用。

    为什么不让前端直接加载候选图 URL：
    1. 外部图片常有防盗链/CORS 限制，直接引用会时好时坏；
    2. 直接引用会把使用者的 IP 暴露给第三方图站；
    3. 排在后面的候选图在真实流程里可能根本不会被下载。
    因此统一由后端代理 + 降采样，并在 staging 里缓存（重复查看不再消赉流量）。
    """
    from PIL import Image

    raw = fetch_source_image(candidate)
    image = to_rgb_on_white(raw)
    if image.width > max_width:
        height = max(1, int(image.height * max_width / image.width))
        image = image.resize((max_width, height), Image.LANCZOS)
    return encode_png(image)
