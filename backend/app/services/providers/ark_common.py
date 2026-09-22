"""火山方舟 HTTP 公共层：超时、有限重试、错误码映射、密钥脱敏。

工程约定：模型调用必须处理超时、失败和有限次数重试（含 SDK 初始化失败），
且错误不泄露上游原始报文与密钥。
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def data_uri(data: bytes, mime: str | None = None) -> str:
    """按魔术字节自动识别图片格式（避免把 JPEG 当 PNG 传，某些上游会直接报错）。"""
    if mime is None:
        if data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data.startswith(b"\x89PNG\r\n"):
            mime = "image/png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _map_http_error(status: int) -> AppError:
    if status in (401, 403):
        return AppError(ErrorCode.UPSTREAM_AUTH_FAILED, detail={"status": status})
    if status == 429:
        return AppError(ErrorCode.UPSTREAM_RATE_LIMITED, detail={"status": status})
    if status == 504:
        return AppError(ErrorCode.UPSTREAM_TIMEOUT, detail={"status": status})
    return AppError(ErrorCode.UPSTREAM_ERROR, detail={"status": status})


class ArkClient:
    """火山方舟（Ark）客户端：Chat Completions（文本/视觉）+ 图片生成。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------------- 内部 ----------------
    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.settings.ark_base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {self.settings.ark_api_key}",
            "Content-Type": "application/json",
        }
        attempts = max(1, self.settings.ark_max_retries + 1)
        last_error: AppError | None = None
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=self.settings.ark_timeout_seconds) as client:
                    response = client.request(method, url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                last_error = AppError(ErrorCode.UPSTREAM_TIMEOUT)
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = AppError(ErrorCode.UPSTREAM_ERROR, detail={"reason": type(exc).__name__})
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise last_error from exc

            if response.status_code >= 400:
                error = _map_http_error(response.status_code)
                if response.status_code in RETRYABLE_STATUS and attempt < attempts:
                    last_error = error
                    time.sleep(0.5 * attempt)
                    continue
                raise error
            try:
                data = response.json()
            except ValueError as exc:
                raise AppError(ErrorCode.UPSTREAM_ERROR, detail={"reason": "非 JSON 响应"}) from exc
            if not isinstance(data, dict):
                raise AppError(ErrorCode.UPSTREAM_ERROR, detail={"reason": "响应结构异常"})
            return data
        raise last_error or AppError(ErrorCode.UPSTREAM_ERROR)

    # ---------------- 对话（文本 / 视觉）----------------
    def chat_text(
        self,
        *,
        model: str,
        system: str,
        user: str,
        images: list[tuple[str, bytes]] | None = None,
        temperature: float = 0.1,
    ) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for label, data in images or []:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": data_uri(data)}})
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content if images else user},
            ],
            "temperature": temperature,
        }
        # 型号校对/画稿质检都是确定性任务，不需要“深度思考”——
        # 关掉它能大幅降低延迟与成本（官方 Chat API 支持 thinking.type=disabled）。
        if self.settings.ark_disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        data = self._request("POST", "/chat/completions", payload)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(ErrorCode.UPSTREAM_ERROR, detail={"reason": "choices 缺失"}) from exc

    # ---------------- 图片生成 ----------------
    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        size: str,
        negative_prompt: str | None = None,
        image: bytes | None = None,
        reference_images: list[bytes] | None = None,
        seed: int | None = None,
        guidance_scale: float | None = None,
        prompt_optimize_mode: str | None = None,
    ) -> bytes:
        """调用图片生成 API（已按官方文档核对字段）。

        官方文档（图片生成 API，Seedream 4.0-5.0）：
        - 参考图字段名是 `image`，类型 `string / string[]`，取值为 URL 或
          `data:image/<格式小写>;base64,` 编码；**多参考图就是给 `image` 传数组**。
        - `size` 在 Seedream 5.0 pro 上可用“分辨率档位”（1K/1.5K/2K）或“宽x高”；
          其他版本用“宽x高”。两种都靠 style 模板里的 provider_params.size 配置。
        - 组图才需要 `sequential_image_generation`；我们只要单张，因此不传。
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        if prompt_optimize_mode:
            # 官方：fast 模式生成耗时更短、效果略低于 standard（pro 支持）
            payload["optimize_prompt_options"] = {"mode": prompt_optimize_mode}

        refs = list(reference_images or [])
        if image is not None:
            refs = [image, *refs]
        if refs:
            encoded = [data_uri(item) for item in refs[:14]]
            # 单图传字符串，多图传数组（官方字段名统一是 image）
            payload["image"] = encoded[0] if len(encoded) == 1 else encoded

        data = self._request("POST", "/images/generations", payload)
        items = data.get("data")
        if not isinstance(items, list) or not items:
            raise AppError(ErrorCode.GENERATE_FAILED, detail={"reason": "响应无图片"})
        first = items[0]
        if isinstance(first, dict) and first.get("b64_json"):
            try:
                return base64.b64decode(first["b64_json"])
            except (ValueError, TypeError) as exc:
                raise AppError(ErrorCode.GENERATE_FAILED, detail={"reason": "b64 解码失败"}) from exc
        url = first.get("url") if isinstance(first, dict) else None
        if url:
            try:
                with httpx.Client(timeout=self.settings.ark_timeout_seconds) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.content
            except httpx.HTTPError as exc:
                raise AppError(ErrorCode.GENERATE_FAILED, detail={"reason": "图片下载失败"}) from exc
        raise AppError(ErrorCode.GENERATE_FAILED, detail={"reason": "响应结构异常"})
