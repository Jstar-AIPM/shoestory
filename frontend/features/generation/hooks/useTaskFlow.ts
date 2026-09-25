"use client";

/**
 * 生成任务流程（真实接口）—— 整个闭环的唯一状态来源
 *
 * 关键约定（/10/11 节）：
 * · 后端是任务状态的**唯一事实来源**，前端不猜、不做乐观更新；
 * · 轮询：1.5s → 失败退避 3/6/12s（上限 15s）→ 终态或等待用户立即停止；
 * · 页面不可见（切标签/最小化）时暂停轮询，恢复可见立刻拉一次；
 * · task_id 写入 URL（?task=）与 localStorage：刷新、离开再回来都能恢复真实状态；
 * · 防重复提交：提交/操作期间禁用按钮（后端也对非法状态返回 409 兜底）。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { LS_ACTIVE_TASK, POLL_BACKOFF_MS, POLL_INTERVAL_MS, POLL_MAX_BACKOFF_MS } from "@/config";
import { ApiError } from "@/lib/api/client";
import type { AppError } from "@/lib/api/errors";
import { createUploadTask } from "@/lib/api/inspect";
import { archiveTask, cancelTask, createTask, getTask, regenerateTask, selectSource } from "@/lib/api/tasks";
import type { TaskOut, UploadTaskPayload } from "@/lib/api/types";
import { isPolling } from "@/lib/state/taskState";

function readTaskIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("task");
}

function syncUrl(taskId: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  window.history.replaceState(null, "", url.toString());
}

export type TaskFlow = ReturnType<typeof useTaskFlow>;

export function useTaskFlow(onArchived?: (shoeId: string) => void, options: { enabled?: boolean } = {}) {
  const enabled = options.enabled ?? true;
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<TaskOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AppError | null>(null);

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failuresRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const applyError = useCallback((cause: unknown) => {
    if (cause instanceof ApiError) setError(cause.appError);
    else
      setError({
        code: "UNKNOWN",
        userMessage: "出了点问题，请把当前页面截图发给 AI。",
        retryable: true,
        status: 0,
      });
  }, []);

  const remember = useCallback((id: string | null) => {
    setTaskId(id);
    syncUrl(id);
    try {
      if (id) window.localStorage.setItem(LS_ACTIVE_TASK, id);
      else window.localStorage.removeItem(LS_ACTIVE_TASK);
    } catch {
      /* 隐私模式下忽略 */
    }
  }, []);

  /** 提交型号 → 创建任务 */
  const submit = useCallback(
    async (query: string) => {
      setSubmitting(true);
      setError(null);
      stopPolling();
      try {
        const created = await createTask(query);
        setTask(created);
        remember(created.task_id);
        return created;
      } catch (cause) {
        applyError(cause);
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [applyError, remember, stopPolling],
  );

  /** 上传图建任务（V2）：图 + 裁切框 + 已体检结论 → 直接进入生成 */
  const submitUpload = useCallback(
    async (payload: UploadTaskPayload) => {
      setSubmitting(true);
      setError(null);
      stopPolling();
      try {
        const created = await createUploadTask(payload);
        setTask(created);
        remember(created.task_id);
        return created;
      } catch (cause) {
        applyError(cause);
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [applyError, remember, stopPolling],
  );

  /** 选源图（三种形态：推荐 / 指定 / 直接用型号生成） */
  const choose = useCallback(
    async (payload: { selected_index?: number; use_model_only?: boolean }) => {
      if (!taskId) return;
      setBusy(true);
      setError(null);
      try {
        await selectSource(taskId, payload);
        setTask(await getTask(taskId));
      } catch (cause) {
        applyError(cause);
      } finally {
        setBusy(false);
      }
    },
    [applyError, taskId],
  );

  const regenerate = useCallback(
    async (payload: { note?: string; emphasis?: string } = {}) => {
      if (!taskId) return;
      setBusy(true);
      setError(null);
      try {
        await regenerateTask(taskId, payload);
        setTask(await getTask(taskId));
      } catch (cause) {
        applyError(cause);
      } finally {
        setBusy(false);
      }
    },
    [applyError, taskId],
  );

  const cancel = useCallback(async () => {
    if (!taskId) return;
    setBusy(true);
    try {
      await cancelTask(taskId);
    } catch (cause) {
      applyError(cause);
    } finally {
      setBusy(false);
      stopPolling();
      remember(null);
      setTask(null);
    }
  }, [applyError, remember, stopPolling, taskId]);

  /** 归档：成功后才清空当前任务（不做乐观更新） */
  const archive = useCallback(
    async (payload: { model_name?: string; date_text?: string | null; story?: string | null }) => {
      if (!taskId) return null;
      setBusy(true);
      setError(null);
      try {
        const result = await archiveTask(taskId, payload);
        stopPolling();
        remember(null);
        setTask(null);
        onArchived?.(result.shoe_id);
        return result;
      } catch (cause) {
        applyError(cause);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [applyError, onArchived, remember, stopPolling, taskId],
  );

  /** 回到空状态（"重新输入"） */
  const reset = useCallback(() => {
    stopPolling();
    remember(null);
    setTask(null);
    setError(null);
    failuresRef.current = 0;
  }, [remember, stopPolling]);

  /** 启动/恢复：URL 优先，其次 localStorage（仅在已登录时执行） */
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const restore = async () => {
      let id = readTaskIdFromUrl();
      if (!id) {
        try {
          id = window.localStorage.getItem(LS_ACTIVE_TASK);
        } catch {
          id = null;
        }
      }
      if (!id) return; // 没有待恢复的任务：什么都不用做（restoring 为派生值）
      try {
        const current = await getTask(id);
        if (cancelled) return;
        setTask(current);
        remember(id);
      } catch {
        // 任务不存在（被清理/换设备）→ 清掉脏记录，不冒充失败
        if (!cancelled) remember(null);
      }
    };
    void restore();
    return () => {
      cancelled = true;
    };
  }, [enabled, remember]);

  /** 轮询：只在"运行中"状态下进行 */
  useEffect(() => {
    if (!task || !taskId || !isPolling(task.state)) {
      stopPolling();
      return;
    }

    let stopped = false;

    const schedule = (delay: number) => {
      if (stopped || typeof document === "undefined") return;
      if (document.hidden) return; // 页面不可见时暂停，恢复可见时由事件触发
      pollRef.current = setTimeout(tick, delay);
    };

    const tick = async () => {
      try {
        const next = await getTask(taskId);
        if (stopped) return;
        failuresRef.current = 0;
        setTask(next);
        setError(null);
        if (isPolling(next.state)) schedule(POLL_INTERVAL_MS);
      } catch (cause) {
        if (stopped) return;
        failuresRef.current += 1;
        applyError(cause);
        const backoff = POLL_BACKOFF_MS[Math.min(failuresRef.current - 1, POLL_BACKOFF_MS.length - 1)];
        schedule(Math.min(backoff, POLL_MAX_BACKOFF_MS));
      }
    };

    const onVisible = () => {
      if (!document.hidden && !stopped) {
        if (pollRef.current) clearTimeout(pollRef.current);
        void tick();
      }
    };

    document.addEventListener("visibilitychange", onVisible);
    schedule(POLL_INTERVAL_MS);

    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      stopPolling();
    };
  }, [applyError, stopPolling, task, taskId]);

  useEffect(() => stopPolling, [stopPolling]);

  // 派生值：不需要额外状态（避免 effect 里同步 setState）
  const restoring = enabled && !task && Boolean(readTaskIdFromUrl());

  return {
    taskId,
    task,
    submitting,
    busy,
    error,
    restoring,
    submit,
    submitUpload,
    choose,
    regenerate,
    archive,
    cancel,
    reset,
    clearError: () => setError(null),
  };
}
