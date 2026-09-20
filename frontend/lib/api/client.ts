/**
 * 统一 HTTP 客户端：超时、JSON 解析、错误归一化集中在这里（前端手册 12.1）
 * 页面组件不直接 fetch。
 */
import { API_BASE, REQUEST_TIMEOUT_MS } from "@/config";
import { NETWORK_ERROR, type AppError, normalizeError } from "@/lib/api/errors";

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export type RequestOptions = {
  method?: Method;
  body?: unknown;
  /** 覆盖默认超时（例如归档写操作可略长） */
  timeoutMs?: number;
  signal?: AbortSignal;
};

/** 业务错误（含 userMessage，可直接展示给用户） */
export class ApiError extends Error {
  readonly appError: AppError;

  constructor(appError: AppError) {
    super(appError.userMessage);
    this.name = "ApiError";
    this.appError = appError;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, timeoutMs = REQUEST_TIMEOUT_MS, signal } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      // 任务状态必须实时，禁止任何缓存
      cache: "no-store",
    });
  } catch {
    throw new ApiError(NETWORK_ERROR);
  } finally {
    clearTimeout(timer);
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(normalizeError(response.status, parsed));
  }
  return parsed as T;
}

/** 图片等二进制资源：直接用同源 URL（后端已做代理与缓存） */
export function absoluteUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) return pathOrUrl;
  return pathOrUrl;
}
