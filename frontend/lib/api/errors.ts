/**
 * 错误归一化（前端手册 12.3）
 *
 * 后端返回 `{error:{code,message,detail}}`，message 已是"中文人话 + 可操作下一步"，
 * 因此前端直接把它当作 userMessage 展示；页面不解析 code，只用它判断是否可重试。
 */
export type AppError = {
  code: string;
  userMessage: string;
  retryable: boolean;
  status: number;
  detail?: Record<string, unknown>;
};

/** 可让用户手动重试的错误（网络抖动/上游临时故障/存储警告） */
const RETRYABLE_CODES = new Set([
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_RATE_LIMITED",
  "UPSTREAM_ERROR",
  "IMAGE_SEARCH_FAILED",
  "GENERATE_FAILED",
  "GENERATE_TIMEOUT",
  "VERIFY_FAILED",
  "STORAGE_CORRUPT",
  "STORAGE_WRITE_FAILED",
  "INTERNAL_ERROR",
]);

export const NETWORK_ERROR: AppError = {
  code: "NETWORK_ERROR",
  userMessage: "网络连接中断了，请检查网络后重试。",
  retryable: true,
  status: 0,
};

/**
 * 请求超时（线上实测：veFaaS 弹性实例空闲后会进入冷启动，
 * 与网关之间那条长连接可能先失效，导致"第一个请求可能要等很久"）。
 * 文案必须让用户知道"等几秒重试就好"，而不是以为产品坏了。
 */
export const TIMEOUT_ERROR: AppError = {
  code: "REQUEST_TIMEOUT",
  userMessage: "服务正在启动（云端实例休眠后首次访问会慢一点），稍等几秒再点一次就好。",
  retryable: true,
  status: 0,
};

export function normalizeError(status: number, body: unknown): AppError {
  const error = (body as { error?: { code?: string; message?: string; detail?: Record<string, unknown> } })?.error;
  if (!error?.code) {
    return {
      code: "UNEXPECTED_RESPONSE",
      userMessage: "服务返回了预期之外的内容，请截图给 AI。",
      retryable: true,
      status,
    };
  }
  return {
    code: error.code,
    userMessage: error.message ?? "出错了，请重试。",
    retryable: RETRYABLE_CODES.has(error.code),
    status,
    detail: error.detail,
  };
}
