"use client";

/**
 * 鞋柜列表（服务端状态）
 *
 * 前端工程约定 9.3 硬要求：loading / empty / failed 必须分开 ——
 * 接口还没回来时绝不能先显示"鞋柜还是空的"。
 *
 * 实现说明：初始加载在 effect 里**订阅 Promise 回调**，而不是在 effect 里同步 setState
 * （React 新规则 react-hooks/set-state-in-effect 要求 effect 只做同步外部系统的工作）。
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { listArchive } from "@/lib/api/archive";
import type { AppError } from "@/lib/api/errors";
import type { ArchiveListResponse, ArchiveListItem } from "@/lib/api/types";

export type CabinetState = "loading" | "empty" | "ready" | "failed";

export function useCabinet({ enabled = true }: { enabled?: boolean } = {}) {
  const [state, setState] = useState<CabinetState>("loading");
  const [items, setItems] = useState<ArchiveListItem[]>([]);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<AppError | null>(null);

  const applySuccess = useCallback((data: ArchiveListResponse) => {
    setItems(data.items);
    setWarning(data.warning ?? null);
    setState(data.items.length > 0 ? "ready" : "empty");
    setError(null);
  }, []);

  const applyFailure = useCallback((cause: unknown) => {
    setState("failed");
    setError(
      cause instanceof ApiError
        ? cause.appError
        : { code: "UNKNOWN", userMessage: "鞋柜读取失败。", retryable: true, status: 0 },
    );
  }, []);

  /** 主动重新拉取（归档成功后、用户点重试时使用） */
  const reload = useCallback(async () => {
    try {
      applySuccess(await listArchive("date"));
    } catch (cause) {
      applyFailure(cause);
    }
  }, [applyFailure, applySuccess]);

  /** 用户主动重试：先进入加载态 */
  const retry = useCallback(async () => {
    setState("loading");
    await reload();
  }, [reload]);

  useEffect(() => {
    // 未登录（或还在校验身份）时不拉取：避免用 401 的失败结果污染界面
    if (!enabled) return;
    let cancelled = false;
    listArchive("date")
      .then((data) => {
        if (!cancelled) applySuccess(data);
      })
      .catch((cause: unknown) => {
        if (!cancelled) applyFailure(cause);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, applyFailure, applySuccess]);

  return { state, items, warning, error, reload, retry };
}
