"use client";

/**
 * 生成中：显示"现在发生什么 / 还要多久 / 我可以做什么"
 * 前端手册 9.2：状态不是一个转圈图标 —— 用后端给的阶段文案 + 已用时 + 可离开提示。
 */
import { useEffect, useState } from "react";

import { Card } from "@/components/ui/Card";
import type { TaskOut } from "@/lib/api/types";

export function GenerationProgress({ task }: { task: TaskOut }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [task.task_id, task.progress?.step]);

  const percent = Math.max(0, Math.min(100, task.progress?.percent ?? 0));
  const label = task.progress?.label ?? "正在处理";
  const interrupted = task.state === "interrupted";

  return (
    <Card className="px-5 py-5 sm:px-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-[17px] font-semibold text-ink">{label}</h2>
        <span className="text-[12.5px] text-faint">已用时 {elapsed} 秒</span>
      </div>

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-black/[0.06]">
        <div
          className="h-full rounded-full bg-[#5865f2] transition-[width] duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>

      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        {interrupted
          ? "服务重启过，这个任务已暂停。已完成的步骤都还在，可以继续或放弃。"
          : "出图通常需要 30 秒左右。可以离开这一页、往下滚动看你的鞋柜，回来接着看进度。"}
      </p>

      {task.upstream_calls > 0 ? (
        <details className="mt-3 text-[12.5px] text-faint">
          <summary className="cursor-pointer select-none">过程详情</summary>
          <p className="mt-2">
            已调用上游 {task.upstream_calls} 次｜调用次数 {task.est_cost_cny}｜当前步骤：{task.progress?.step ?? "—"}
          </p>
        </details>
      ) : null}
    </Card>
  );
}
