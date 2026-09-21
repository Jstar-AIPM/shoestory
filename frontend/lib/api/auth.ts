/** 鉴权接口：邀请码登录 / 当前身份 / 退出 */
import { request } from "@/lib/api/client";
import type { CodeInfo, LoginOut, MeOut } from "@/lib/api/types";

export function login(code: string): Promise<LoginOut> {
  return request<LoginOut>("/auth/login", { method: "POST", body: { code } });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/auth/logout", { method: "POST" });
}

export function me(): Promise<MeOut> {
  return request<MeOut>("/auth/me");
}

/** 管理员：邀请码管理 */
export function listCodes(): Promise<{ total: number; items: CodeInfo[] }> {
  return request("/admin/codes");
}

export function createCode(payload: {
  note?: string;
  max_uses?: number | null;
  ttl_days?: number | null;
}): Promise<CodeInfo> {
  return request("/admin/codes", { method: "POST", body: payload });
}

export function revokeCode(code: string): Promise<CodeInfo> {
  return request(`/admin/codes/${encodeURIComponent(code)}/revoke`, { method: "POST" });
}

export function purgeOwner(ownerId: string): Promise<{ owner_id: string; removed_files: number; message: string }> {
  return request(`/admin/owners/${encodeURIComponent(ownerId)}`, { method: "DELETE" });
}
