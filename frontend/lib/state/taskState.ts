/**
 * 后端状态 → 前端统一状态映射（纯函数，重点单测）
 *
 * 为什么单独抽出来：后端 15 个状态与前端 12 个统一状态不是一一对应；
 * 页面不应该直接判断后端枚举（前端手册 9.1：未知状态必须安全兜底，不能猜）。
 */
import type { TaskState } from "@/lib/api/types";

export type UiTaskState =
  | "idle"
  | "submitting"
  | "running"
  | "waiting_user"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "disconnected"
  | "unknown";

const MAP: Record<TaskState, UiTaskState> = {
  created: "submitting",
  resolving: "running",
  // 文搜图 + 视觉预筛在后台跑（线上约 58s）：对用户就是"正在处理"，必须继续轮询
  searching_source: "running",
  model_not_found: "waiting_user",
  resolve_failed: "waiting_user",
  awaiting_source_confirm: "waiting_user",
  preprocessing: "running",
  generating: "running",
  refining: "running",
  verifying: "running",
  interrupted: "disconnected",
  awaiting_effect_confirm: "waiting_user",
  archiving: "running",
  archived: "succeeded",
  failed: "failed",
  cancelled: "cancelled",
};

/** 需要轮询的状态（等待用户确认时不需要轮询：状态不会自己变） */
const POLLING: ReadonlySet<UiTaskState> = new Set<UiTaskState>([
  "submitting",
  "running",
  "disconnected",
]);

export function toUiState(state: string | null | undefined): UiTaskState {
  if (!state) return "idle";
  return MAP[state as TaskState] ?? "unknown";
}

export function isPolling(state: string | null | undefined): boolean {
  return POLLING.has(toUiState(state));
}

export function isTerminal(state: string | null | undefined): boolean {
  const ui = toUiState(state);
  return ui === "succeeded" || ui === "failed" || ui === "cancelled";
}

export function isWaitingUser(state: string | null | undefined): boolean {
  return toUiState(state) === "waiting_user";
}
