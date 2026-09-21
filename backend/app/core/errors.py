"""统一错误码与错误结构：用户只看到中文人话，永不看到堆栈。"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    # 输入 / 状态
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_STATE = "INVALID_STATE"
    STYLE_NOT_FOUND = "STYLE_NOT_FOUND"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    ARCHIVE_NOT_FOUND = "ARCHIVE_NOT_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    ARTWORK_NOT_FOUND = "ARTWORK_NOT_FOUND"
    ARTWORK_INVALID = "ARTWORK_INVALID"
    # 权限 / 安全
    MANUAL_SOURCE_DISABLED = "MANUAL_SOURCE_DISABLED"
    UNSAFE_PATH = "UNSAFE_PATH"
    UNSAFE_OWNER_ID = "UNSAFE_OWNER_ID"
    UNSUPPORTED_IMAGE = "UNSUPPORTED_IMAGE"
    # 上游 / 模型
    UPSTREAM_AUTH_FAILED = "UPSTREAM_AUTH_FAILED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    IMAGE_SEARCH_EMPTY = "IMAGE_SEARCH_EMPTY"
    IMAGE_SEARCH_FAILED = "IMAGE_SEARCH_FAILED"
    GENERATE_FAILED = "GENERATE_FAILED"
    GENERATE_TIMEOUT = "GENERATE_TIMEOUT"
    VERIFY_FAILED = "VERIFY_FAILED"
    # 成本 / 存储
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    STORAGE_CORRUPT = "STORAGE_CORRUPT"
    STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
    SCHEMA_TOO_NEW = "SCHEMA_TOO_NEW"
    # 鉴权 / 额度（阶段 4）
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CODE_INVALID = "CODE_INVALID"
    CODE_EXPIRED = "CODE_EXPIRED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    FORBIDDEN = "FORBIDDEN"
    # 兜底
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 默认 HTTP 状态码（业务失败用 2xx + state 表达，见阶段文档 7.1）
_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.INVALID_STATE: 409,
    ErrorCode.STYLE_NOT_FOUND: 422,
    ErrorCode.CONFIRM_REQUIRED: 409,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.ARCHIVE_NOT_FOUND: 404,
    ErrorCode.SOURCE_NOT_FOUND: 422,
    ErrorCode.ARTWORK_NOT_FOUND: 404,
    ErrorCode.ARTWORK_INVALID: 422,
    ErrorCode.MANUAL_SOURCE_DISABLED: 403,
    ErrorCode.UNSAFE_PATH: 422,
    ErrorCode.UNSAFE_OWNER_ID: 422,
    ErrorCode.UNSUPPORTED_IMAGE: 422,
    ErrorCode.UPSTREAM_AUTH_FAILED: 502,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.UPSTREAM_RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.LLM_OUTPUT_INVALID: 502,
    ErrorCode.IMAGE_SEARCH_EMPTY: 422,
    ErrorCode.IMAGE_SEARCH_FAILED: 502,
    ErrorCode.GENERATE_FAILED: 502,
    ErrorCode.GENERATE_TIMEOUT: 504,
    ErrorCode.VERIFY_FAILED: 502,
    ErrorCode.BUDGET_EXCEEDED: 429,
    ErrorCode.STORAGE_CORRUPT: 500,
    ErrorCode.STORAGE_WRITE_FAILED: 507,
    ErrorCode.SCHEMA_TOO_NEW: 409,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.CODE_INVALID: 401,
    ErrorCode.CODE_EXPIRED: 410,
    ErrorCode.QUOTA_EXCEEDED: 429,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.INTERNAL_ERROR: 500,
}

# 用户可见文案：中文人话 + 可操作的下一步
_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_INPUT: "输入不符合要求，请检查后重试。",
    ErrorCode.INVALID_STATE: "这一步当前还不能操作，请刷新页面看最新状态。",
    ErrorCode.STYLE_NOT_FOUND: "这个风格还不存在，请换一个风格。",
    ErrorCode.CONFIRM_REQUIRED: "删除前需要二次确认。",
    ErrorCode.TASK_NOT_FOUND: "找不到这个生成任务，请重新开始。",
    ErrorCode.ARCHIVE_NOT_FOUND: "找不到这双鞋，可能已被删除。",
    ErrorCode.SOURCE_NOT_FOUND: "找不到这张候选图，请重新选一张。",
    ErrorCode.ARTWORK_NOT_FOUND: "这张画稿不存在，请重新生成。",
    ErrorCode.ARTWORK_INVALID: "画稿不符合规格（3:2 白底纯黑白），已拦截，请重新生成。",
    ErrorCode.MANUAL_SOURCE_DISABLED: "手动指定源图已关闭，请用型号检索。",
    ErrorCode.UNSAFE_PATH: "这个文件路径不被允许，请放在约定的目录内。",
    ErrorCode.UNSAFE_OWNER_ID: "身份标识不合法。",
    ErrorCode.UNSUPPORTED_IMAGE: "这个文件不是可用的图片，请换一张（JPG/PNG，边长≥400px，≤10MB）。",
    ErrorCode.UPSTREAM_AUTH_FAILED: "模型或搜索的密钥不可用，请检查 .env 里的配置。",
    ErrorCode.UPSTREAM_TIMEOUT: "上游响应超时，稍后可以重试。",
    ErrorCode.UPSTREAM_RATE_LIMITED: "上游触发限流，请稍后重试。",
    ErrorCode.UPSTREAM_ERROR: "上游服务返回异常，稍后可以重试。",
    ErrorCode.LLM_OUTPUT_INVALID: "模型返回的格式不符合要求，已重试仍失败，请再试一次。",
    ErrorCode.IMAGE_SEARCH_EMPTY: "没找到这个型号的清晰图片，请确认型号写法后重试（或使用“高级：手动给一张源图”）。",
    ErrorCode.IMAGE_SEARCH_FAILED: "搜图服务暂时不可用，稍后可以重试。",
    ErrorCode.GENERATE_FAILED: "线稿生成失败，可以点“重新生成”再试一次。",
    ErrorCode.GENERATE_TIMEOUT: "线稿生成超时，可以点“重新生成”再试一次。",
    ErrorCode.VERIFY_FAILED: "质检环节出错，可以点“重新生成”再试一次。",
    ErrorCode.BUDGET_EXCEEDED: "本次任务的调用次数已达上限（成本护栏），请重新开始或稍后再试。",
    ErrorCode.STORAGE_CORRUPT: "本地档案文件损坏，已备份原文件并以空档案继续，请告知 AI 处理。",
    ErrorCode.STORAGE_WRITE_FAILED: "保存失败（存储不可写），请检查磁盘空间或权限。",
    ErrorCode.SCHEMA_TOO_NEW: "数据版本比当前程序新，请升级程序后再操作。",
    ErrorCode.AUTH_REQUIRED: "请先用邀请码进入。",
    ErrorCode.CODE_INVALID: "邀请码不对，请检查后重新输入。",
    ErrorCode.CODE_EXPIRED: "这个邀请码已过期。已归档的鞋柜仍然可以查看。",
    ErrorCode.QUOTA_EXCEEDED: "这个邀请码的生成次数已用完。已归档的鞋柜仍然可以查看。",
    ErrorCode.FORBIDDEN: "没有权限执行这个操作。",
    ErrorCode.INTERNAL_ERROR: "服务出了点问题，请把当前页面截图发给 AI。",
}


class AppError(Exception):
    """业务错误：带错误码、中文文案与可选的结构化 detail。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message or _MESSAGE.get(code, "出错了，请重试。")
        self.detail = detail or {}
        self.status_code = status_code or _DEFAULT_STATUS.get(code, 400)
        super().__init__(f"{code.value}: {self.message}")

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.detail:
            body["detail"] = self.detail
        return {"error": body}


def message_for(code: ErrorCode) -> str:
    return _MESSAGE.get(code, "出错了，请重试。")
