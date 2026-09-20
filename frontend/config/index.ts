/**
 * 集中配置：页面不直接拼接接口地址（前端手册 12.1）
 *
 * 接口统一走同源路径 `/api/v1`，由 next.config 的 rewrites 代理到后端。
 * 这样开发与生产都是同源请求：无 CORS、Cookie 鉴权可用、地址只在一处配置。
 */
export const API_BASE = "/api/v1";

/** 轮询间隔与退避（前端手册 10.3：明确间隔 + 退避 + 就绪即停） */
export const POLL_INTERVAL_MS = 1500;
export const POLL_BACKOFF_MS = [3000, 6000, 12000];
export const POLL_MAX_BACKOFF_MS = 15000;

/** 普通请求超时（毫秒） */
export const REQUEST_TIMEOUT_MS = 30_000;

/** localStorage 键：仅用于"刷新后找回进行中的任务" */
export const LS_ACTIVE_TASK = "lvli.activeTaskId";
