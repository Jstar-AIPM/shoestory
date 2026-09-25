/** 任务相关接口（集中管理，页面不拼地址） */
import { request } from "@/lib/api/client";
import type { ArchiveDetail, DateParseResponse, TaskOut } from "@/lib/api/types";

export function createTask(query: string, signal?: AbortSignal): Promise<TaskOut> {
  return request<TaskOut>("/tasks", { method: "POST", body: { query }, signal });
}

export function getTask(taskId: string, signal?: AbortSignal): Promise<TaskOut> {
  return request<TaskOut>(`/tasks/${taskId}`, { signal });
}

/** 三种选源形态统一入口：不传参数 = 用系统推荐的那张（"就是这双"） */
export function selectSource(
  taskId: string,
  payload: { selected_index?: number; use_model_only?: boolean },
): Promise<{ task_id: string; state: string; message: string }> {
  return request(`/tasks/${taskId}/source`, { method: "POST", body: payload });
}

export function regenerateTask(
  taskId: string,
  note?: string,
): Promise<{ task_id: string; state: string; message: string }> {
  return request(`/tasks/${taskId}/regenerate`, { method: "POST", body: { note } });
}

export function cancelTask(taskId: string): Promise<{ task_id: string; state: string; message: string }> {
  return request(`/tasks/${taskId}/cancel`, { method: "POST" });
}

export function archiveTask(
  taskId: string,
  payload: {
    model_name?: string;
    date_text?: string | null;
    story?: string | null;
    attempt?: number;
  },
): Promise<{ shoe_id: string; artwork_url: string; date_sort_key: string | null; created_at: string }> {
  return request(`/tasks/${taskId}/archive`, { method: "POST", body: payload });
}

export function parseDateText(text: string): Promise<DateParseResponse> {
  return request<DateParseResponse>(`/date-parse?text=${encodeURIComponent(text)}`);
}

/** 候选图预览（后端代理 + 缓存；不直连外部图站） */
export function candidatePreviewUrl(taskId: string, index: number): string {
  return `/api/v1/tasks/${taskId}/candidates/${index}.png`;
}

/** 某次生成的画稿（历史尝试也用这个） */
export function artworkUrl(taskId: string, attempt: number): string {
  return `/api/v1/tasks/${taskId}/artworks/${attempt}.png`;
}

export type { TaskOut, ArchiveDetail };
