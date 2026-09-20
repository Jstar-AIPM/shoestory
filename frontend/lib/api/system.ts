/** 系统接口：健康检查（驱动顶栏"真实模型 / 演示模式"徽标） */
import { request } from "@/lib/api/client";
import type { HealthResponse } from "@/lib/api/types";

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}
