"use client";

/**
 * 生成中：CV 草稿先「扫过式揭示」出来并叠上马赛克生成动效，后台同时跑 AI 正式稿。
 *
 * 三件事（2026-09-23 产品反馈后调整）：
 * 1. **草稿必须一眼看出是草稿**：浅灰铅笔感 + 描图纸方格 + 右上角「草稿预览」角标；
 * 2. **状态紧贴画稿下方**：用 StatusBar 小状态条（顶栏不再显示状态）；
 * 3. **生成感**：扫过式揭示 + 马赛克随机闪烁（DraftMosaic），正式稿完成时整体淡入替换。
 */
import { useEffect, useState } from "react";

import { StatusBar } from "@/components/ui/StatusBar";
import type { TaskOut } from "@/lib/api/types";

import { DraftMosaic } from "./DraftMosaic";

/** 草稿出现前的等待（秒）：草稿算得很快，立刻显示会让人以为"就这么糊"、然后干等半天（2026-09-23 反馈）*/
const DRAFT_REVEAL_DELAY_MS = 6000;

export function GenerationProgress({ task }: { task: TaskOut }) {
  const [elapsed, setElapsed] = useState(0);
  const [draftRevealed, setDraftRevealed] = useState(false);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [task.task_id, task.progress?.step]);

  // 草稿延后出现：先让人看到"正在准备"，等几秒再以渐显的方式把草稿推上来
  useEffect(() => {
    if (!task.draft_url) return;
    const timer = setTimeout(() => setDraftRevealed(true), DRAFT_REVEAL_DELAY_MS);
    return () => clearTimeout(timer);
  }, [task.task_id, task.draft_url]);

  const percent = Math.max(0, Math.min(100, task.progress?.percent ?? 0));
  const label = task.progress?.label ?? "正在处理";
  const interrupted = task.state === "interrupted";
  const draftReady = Boolean(task.draft_url) && draftRevealed;

  const statusLabel = interrupted ? "服务重启了，任务已暂停（进度都还在）" : label;
  const waitingForDraft = Boolean(task.draft_url) && !draftRevealed;

  return (
    <div className="mx-auto w-full max-w-[720px] space-y-3">
      {draftReady ? (
        <>
          <div className="draft-sheet draft-appear relative overflow-hidden rounded-[var(--radius-card)] border border-line">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={task.draft_url ?? ""}
              alt="线稿草稿（预览，不是最终稿）"
              className="draft-reveal frame-3x2"
              style={{ objectFit: "contain" }}
            />
            <DraftMosaic active={!interrupted} />
            <span className="draft-badge">草稿预览</span>
            <span className="draft-scanline" aria-hidden />
          </div>

          <StatusBar
            label={statusLabel}
            percent={percent}
            meta={`已用时 ${elapsed} 秒`}
            pulse={!interrupted}
          />

          <p className="text-center text-[12.5px] leading-relaxed text-faint">
            {interrupted ? (
              "已完成的步骤都还在，可以继续或放弃。"
            ) : (
              <>
                上面是<strong className="text-muted">草稿预览</strong>（本机 1 秒算出来的），
                正式线稿正在精修，完成后会自动替换。
              </>
            )}
          </p>
        </>
      ) : waitingForDraft ? (
        <>
          <div className="draft-sheet draft-appear relative overflow-hidden rounded-[var(--radius-card)] border border-line">
            <div className="frame-3x2 flex items-center justify-center">
              <span className="text-[13px] text-[#6b6b66]">正在准备画面…</span>
            </div>
          </div>
          <StatusBar label={statusLabel} percent={percent} meta={`已用时 ${elapsed} 秒`} pulse={!interrupted} />
          <p className="text-center text-[12.5px] leading-relaxed text-faint">
            约 5–10 秒后会先给您看一版草稿，正式线稿随后替换它。
          </p>
        </>
      ) : (
        <div className="rounded-[var(--radius-card)] border border-line bg-[rgba(255,255,255,0.04)] px-4 py-4">
          <StatusBar label={statusLabel} percent={percent} meta={`已用时 ${elapsed} 秒`} pulse={!interrupted} />
          <p className="mt-3 text-[13px] leading-relaxed text-muted">
            {interrupted
              ? "服务重启过，这个任务已暂停。已完成的步骤都还在，可以继续或放弃。"
              : "出图通常需要 30 秒左右。可以离开这一页、往下滚动看您的鞋柜，回来接着看进度。"}
          </p>
          {task.upstream_calls > 0 ? (
            <details className="mt-3 text-[12.5px] text-faint">
              <summary className="cursor-pointer select-none">过程详情</summary>
              <p className="mt-2">
                已调用上游 {task.upstream_calls} 次｜当前步骤：
                {task.progress?.step ?? "—"}
              </p>
            </details>
          ) : null}
        </div>
      )}
    </div>
  );
}
