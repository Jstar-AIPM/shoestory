/**
 * 统一 HTTP 客户端：超时、JSON 解析、错误归一化集中在这里（前端工程约定 12.1）
 * 页面组件不直接 fetch。
 */
import { API_BASE, REQUEST_TIMEOUT_MS } from "@/config";
import {
  NETWORK_ERROR,
  TIMEOUT_ERROR,
  type AppError,
  normalizeError,
} from "@/lib/api/errors";

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export type RequestOptions = {
  method?: Method;
  body?: unknown;
  /** 覆盖默认超时（例如归档写操作可略长） */
  timeoutMs?: number;
  signal?: AbortSignal;
  /** 超时后自动重试次数（仅同请求安全时使用；默认 GET 重试 2 次，写操作不重试） */
  retriesOnTimeout?: number;
};

/** 超时重试的退避（毫秒）："服务正在启动"时给实例一点时间 */
const TIMEOUT_RETRY_DELAYS_MS = [1200, 3000];

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
  const { signal } = options;
  // 幂等（GET）才允许超时重试：
  // POST /tasks 这类写操作重试会造成重复扣额度/重复花钱，必须由用户手动决定。
  const method = options.method ?? "GET";
  const retries =
    options.retriesOnTimeout ?? (method === "GET" ? TIMEOUT_RETRY_DELAYS_MS.length : 0);

  let lastError: ApiError = new ApiError(TIMEOUT_ERROR);
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await attemptRequest<T>(path, options);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      lastError = error;
      const isTimeout = error.appError.code === TIMEOUT_ERROR.code;
      const canRetry = isTimeout && attempt < retries && !signal?.aborted;
      if (!canRetry) break;
      await new Promise((resolve) => setTimeout(resolve, TIMEOUT_RETRY_DELAYS_MS[attempt] ?? 3000));
    }
  }
  throw lastError;
}

async function attemptRequest<T>(path: string, options: RequestOptions): Promise<T> {
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
    // 区分"超时"与"断网"：超时在线上是冷启动/长连接失效，用户重试就能好
    throw new ApiError(controller.signal.aborted && !signal?.aborted ? TIMEOUT_ERROR : NETWORK_ERROR);
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
