/** 鞋柜相关接口 */
import { request } from "@/lib/api/client";
import type { ArchiveDetail, ArchiveListResponse } from "@/lib/api/types";

export function listArchive(sort: "date" | "created" = "date"): Promise<ArchiveListResponse> {
  return request<ArchiveListResponse>(`/archive?sort=${sort}&limit=200`);
}

export function getArchive(shoeId: string, sort: "date" | "created" = "date"): Promise<ArchiveDetail> {
  return request<ArchiveDetail>(`/archive/${shoeId}?sort=${sort}`);
}

export function patchArchive(
  shoeId: string,
  payload: { model_name?: string; date_text?: string | null; story?: string | null },
): Promise<ArchiveDetail> {
  // ⚠️ 用 POST 而不是 PATCH：线上的 veFaaS API 网关**不转发 PATCH**
  // （实测：PATCH 任何路径都返回空响应体的 404），会让保存永远失败。
  // 后端同时保留了 PATCH 版本（语义正确），网关支持后可以切回去。
  return request<ArchiveDetail>(`/archive/${shoeId}/edit`, { method: "POST", body: payload });
}

export function deleteArchive(shoeId: string): Promise<{ deleted: boolean; removed_files: number }> {
  // 后端要求显式二次确认（前端已有确认弹窗）
  return request(`/archive/${shoeId}?confirm=true`, { method: "DELETE" });
}

export function archiveArtworkUrl(shoeId: string): string {
  return `/api/v1/archive/${shoeId}/artwork.png`;
}
