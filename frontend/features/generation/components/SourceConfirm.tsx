"use client";

/**
 * 源图确认（三种形态，全部来自后端真实判定）
 *   single      —— 只给 1 张推荐图："就是这双，开始画"
 *   model_only  —— 搜到的图都不适合：默认"直接用型号生成"，也可展开自己挑
 *   choose      —— 置信度不足：展开多张（带可用性与理由）
 * 图片放在"墙上"（深色底更像作品），说明与按钮放在"纸上"（易读）。
 */
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/StatusChip";
import { candidatePreviewUrl } from "@/lib/api/tasks";
import type { SourceCandidate, TaskOut } from "@/lib/api/types";
import { cn } from "@/lib/utils/cn";

function CandidateImage({
  taskId,
  candidate,
  selected,
  onSelect,
  compact,
}: {
  taskId: string;
  candidate: SourceCandidate;
  selected?: boolean;
  onSelect?: () => void;
  compact?: boolean;
}) {
  const reason = candidate.screen_reason;
  const usable = candidate.screen_usable;
  return (
    <button
      type="button"
      onClick={onSelect}
      data-theme="card-paper"
      className={cn(
        "block w-full overflow-hidden rounded-[var(--radius-card)] border-2 bg-surface text-left transition-colors",
        selected ? "border-[#5865f2]" : "border-line hover:border-[#5865f2]/50",
      )}
    >
      <span className="frame-3x2 block border-b border-line">
        {/* 候选图由后端代理并缓存，不直连外部图站 */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={candidatePreviewUrl(taskId, candidate.index)} alt={`候选参考图 ${candidate.index + 1}`} />
      </span>
      {!compact ? (
        <span className="block px-3 py-2">
          <span className="flex items-center gap-2">
            <StatusChip tone={usable ? "success" : "warn"}>
              {usable ? "单只 · 正侧面" : "可能不适合做参考"}
            </StatusChip>
            <span className="text-[12px] text-faint">
              {candidate.width ?? "?"}×{candidate.height ?? "?"}
            </span>
          </span>
          {reason ? <span className="mt-1.5 block text-[12.5px] text-muted">{reason}</span> : null}
        </span>
      ) : null}
    </button>
  );
}

export function SourceConfirm({
  task,
  busy,
  onChoose,
  onReset,
}: {
  task: TaskOut;
  busy: boolean;
  onChoose: (payload: { selected_index?: number; use_model_only?: boolean }) => void;
  onReset: () => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(task.source_mode === "choose");
  const candidates = task.source_candidates ?? [];
  const recommended = task.recommended_index ?? 0;
  const isModelOnly = task.source_mode === "model_only";

  if (!candidates.length && !isModelOnly) {
    return (
      <Card className="px-5 py-5 sm:px-6">
        <h2 className="text-[17px] font-semibold text-ink">没找到这款鞋的清晰图片</h2>
        <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
          {task.error?.message ?? "搜图暂时没有结果。"} 可以换个型号写法再试，或直接用型号生成线稿。
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => onChoose({ use_model_only: true })} disabled={busy}>
            直接用型号生成（推荐）
          </Button>
          <Button variant="ghost" onClick={onReset}>
            重新输入型号
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* 墙上：候选图 */}
      <div className={cn("mx-auto w-full", isModelOnly && !expanded ? "hidden" : "max-w-[560px]")}>
        {task.source_mode === "single" && !expanded ? (
          <CandidateImage
            taskId={task.task_id}
            candidate={candidates[recommended] ?? candidates[0]}
            selected
            compact
          />
        ) : (
          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
            {candidates.map((candidate) => (
              <CandidateImage
                key={candidate.index}
                taskId={task.task_id}
                candidate={candidate}
                selected={picked === candidate.index}
                onSelect={() => setPicked(candidate.index)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 纸上：先给校对结果，再给说明与操作（用户必须能看到"识别成什么"） */}
      <Card className="px-5 py-5 sm:px-6">
        <div className="mb-3 flex flex-wrap items-center gap-2.5 border-b border-line pb-3">
          <StatusChip tone="neutral">识别为</StatusChip>
          <span className="text-[15px] font-semibold text-ink">
            {task.normalize?.normalized ?? task.query}
          </span>
          {task.normalize?.brand ? (
            <span className="text-[12.5px] text-faint">{task.normalize.brand}</span>
          ) : null}
          {task.normalize?.note ? (
            <span className="w-full text-[12.5px] text-muted sm:w-auto">{task.normalize.note}</span>
          ) : null}
        </div>
        {isModelOnly && !expanded ? (
          <>
            <h2 className="text-[17px] font-semibold text-ink">搜到的图都不太适合当参考</h2>
            <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
              原因：{candidates.find((c) => c.screen_reason)?.screen_reason ?? "不是单只正侧面图"}。
              直接用型号生成的效果通常更好（实测 Logo 与鞋型都更准），也可以展开候选图自己挑一张。
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="primary"
                className="btn-blurple"
                onClick={() => onChoose({ use_model_only: true })}
                disabled={busy}
              >
                直接用型号生成（推荐）
              </Button>
              <Button variant="secondary" onClick={() => setExpanded(true)}>
                展开候选图，我自己挑
              </Button>
              <Button variant="ghost" onClick={onReset}>
                重新输入型号
              </Button>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-[17px] font-semibold text-ink">
              {task.source_mode === "single" && !expanded ? "确认一下：是这双吗？" : "请挑一张作为参考图"}
            </h2>
            <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
              {task.source_mode === "single" && !expanded
                ? "确认只需 1 秒，能避免画错、白花一次生成额度。（系统已替你选好参考图）"
                : "点一张你想用作参考的图，再开始画。选错会让线稿偏离原鞋。"}
            </p>
            {task.error ? (
              <div className="mt-3">
                <Alert tone="warn" title="上次操作没有成功">{task.error.message}</Alert>
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="primary"
                className="btn-blurple"
                disabled={busy || (task.source_mode !== "single" && picked === null)}
                onClick={() => onChoose(picked === null ? {} : { selected_index: picked })}
              >
                {task.source_mode === "single" && !expanded ? "就是这双，开始画" : "用这张开始画"}
              </Button>
              {task.source_mode === "single" && candidates.length > 1 ? (
                <Button variant="secondary" onClick={() => setExpanded(true)}>
                  换一张参考图
                </Button>
              ) : null}
              {candidates.length > 1 && expanded ? (
                <Button variant="secondary" onClick={() => onChoose({ use_model_only: true })} disabled={busy}>
                  都不用，直接用型号生成
                </Button>
              ) : null}
              <Button variant="ghost" onClick={onReset}>
                不是这双 / 重新输入
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
