/** 上传图体检（V2 输入方式）相关接口 */
import { request } from "@/lib/api/client";
import type { CropBox, InspectResponse, TaskOut, UploadTaskPayload } from "@/lib/api/types";

/**
 * 体检一张上传图。
 * - 不带 crop：只跑 CV 主体定位（本机计算），返回「建议裁切框」；
 * - 带 crop：裁切后调用一次视觉模型（本机计算），返回三档结论 + 品牌/型号/Logo/文字。
 */
export function inspectImage(imageBase64: string, crop?: CropBox): Promise<InspectResponse> {
  return request<InspectResponse>("/inspect", {
    method: "POST",
    body: crop ? { image_base64: imageBase64, crop } : { image_base64: imageBase64 },
  });
}

/** 上传图建任务（V2）：图 + 裁切框 + 已体检结论 → 直接进入生成。 */
export function createUploadTask(payload: UploadTaskPayload): Promise<TaskOut> {
  return request<TaskOut>("/tasks/upload", { method: "POST", body: payload });
}
