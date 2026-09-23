"use client";

/**
 * 上传 → 体检 → 确认 的前置流程（V2 输入方式）。
 *
 * 与 useTaskFlow 的分工：useTaskFlow 管「任务创建后」的轮询与操作；
 * 这里管「任务创建前」的图选择、裁切与三档判定，确认后把图 + 裁切框 + 体检结论
 * 交给 useTaskFlow.submitUpload 建任务。
 *
 * 状态机：empty → cropping（先只跑 CV 定位，给建议框）→ 确认框选 → 体检
 *   → rejected（明确不是鞋）/ cropping（框里多只，重新框）/ confirm（是鞋，可开画）。
 */
import { useCallback, useState } from "react";

import { ApiError } from "@/lib/api/client";
import type { AppError } from "@/lib/api/errors";
import { inspectImage } from "@/lib/api/inspect";
import type { CropBox, InspectResponse, TaskOut, UploadTaskPayload } from "@/lib/api/types";
import { fileToResizedDataUrl, pickImageFile } from "@/lib/utils/image";

export type UploadPhase = "empty" | "cropping" | "rejected" | "confirm";

export type UploadFlow = ReturnType<typeof useUploadFlow>;

function toAppError(cause: unknown): AppError {
  if (cause instanceof ApiError) return cause.appError;
  return {
    code: "UNKNOWN",
    userMessage: "图片处理出了点问题，请换一张再试。",
    retryable: true,
    status: 0,
  };
}

export function useUploadFlow(onStart?: (payload: UploadTaskPayload) => Promise<TaskOut | null>) {
  const [phase, setPhase] = useState<UploadPhase>("empty");
  const [image, setImage] = useState<{ dataUrl: string; width: number; height: number } | null>(null);
  const [crop, setCrop] = useState<CropBox | null>(null);
  const [guide, setGuide] = useState<string>("");
  const [inspect, setInspect] = useState<InspectResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AppError | null>(null);

  const applyError = useCallback((cause: unknown) => {
    setError(toAppError(cause));
  }, []);

  /** ① 选图：压到长边 ≤1600，先跑一次 CV 定位（本机计算）拿建议框 */
  const pickFile = useCallback(
    async (file: File | null) => {
      if (!file || !file.type.startsWith("image/")) {
        setError({ code: "INVALID_INPUT", userMessage: "请选择一张图片（JPG / PNG / WebP）。", retryable: false, status: 400 });
        return;
      }
      setBusy(true);
      setError(null);
      setInspect(null);
      try {
        const resized = await fileToResizedDataUrl(file);
        setImage(resized);
        setCrop(null);
        setPhase("cropping");
        // 第一次只做 CV 定位，不调视觉模型（省钱）
        const first = await inspectImage(resized.dataUrl);
        // 找不到候选（none）时给一个居中默认框，用户仍可手动拖拽调整
        const fallback: CropBox = {
          x: Math.round(resized.width * 0.1),
          y: Math.round(resized.height * 0.1),
          w: Math.round(resized.width * 0.8),
          h: Math.round(resized.height * 0.8),
        };
        setCrop(first.crop ?? fallback);
        setGuide(first.message);
      } catch (cause) {
        applyError(cause);
        setPhase("empty");
        setImage(null);
      } finally {
        setBusy(false);
      }
    },
    [applyError],
  );

  /** ② 确认框选 → 裁切后体检（一次视觉调用） */
  const confirmCrop = useCallback(async () => {
    if (!image || !crop) return;
    setBusy(true);
    setError(null);
    try {
      const result = await inspectImage(image.dataUrl, crop);
      setInspect(result);
      if (result.tier === "not_shoe") {
        setPhase("rejected");
      } else if (result.tier === "multi") {
        setGuide(result.message);
        setCrop(result.crop ?? crop);
        setPhase("cropping");
      } else {
        setPhase("confirm");
      }
    } catch (cause) {
      applyError(cause);
    } finally {
      setBusy(false);
    }
  }, [applyError, crop, image]);

  const reset = useCallback(() => {
    setPhase("empty");
    setImage(null);
    setCrop(null);
    setGuide("");
    setInspect(null);
    setError(null);
  }, []);

  /** 从「确认」退回「重新框选」（保留图与框） */
  const reCrop = useCallback(() => {
    setPhase("cropping");
  }, []);

  /** ③ 开始画：把「图 + 裁切框 + 体检结论」交给上层建任务（消耗 1 次生成额度） */
  const start = useCallback(async () => {
    if (!image || !crop || !inspect || !onStart) return null;
    setBusy(true);
    setError(null);
    try {
      const payload: UploadTaskPayload = {
        image_base64: image.dataUrl,
        crop,
        inspect: {
          display_name: inspect.detail.display_name,
          brand: inspect.detail.brand,
          model_name: inspect.detail.model_name,
          colorway: inspect.detail.colorway,
          logo_type: inspect.detail.logo_type,
          logo_position: inspect.detail.logo_position,
          logo_fill_required: inspect.detail.logo_fill_required,
          texts: inspect.detail.texts,
          text_stamps: inspect.detail.text_stamps ?? [],
          shoe_count: inspect.detail.shoe_count,
        },
      };
      const task = await onStart(payload);
      if (task) reset(); // 建任务成功 → 清空上传流程，交给 useTaskFlow 轮询
      return task;
    } catch (cause) {
      applyError(cause);
      return null;
    } finally {
      setBusy(false);
    }
  }, [applyError, crop, image, inspect, onStart, reset]);

  /** 供拖拽/粘贴/相册入口统一调用 */
  const acceptFiles = useCallback(
    (files: FileList | File[] | null | undefined) => {
      const file = pickImageFile(files);
      if (file) void pickFile(file);
    },
    [pickFile],
  );

  return {
    phase,
    image,
    crop,
    guide,
    inspect,
    busy,
    error,
    setCrop,
    acceptFiles,
    confirmCrop,
    start,
    reCrop,
    reset,
    clearError: () => setError(null),
  };
}
