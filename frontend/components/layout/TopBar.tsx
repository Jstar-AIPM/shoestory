/**
 * 顶栏：品牌 + 运行模式徽标 + 「正在生成」横幅
 *
 * 说明（对应前端适配声明 4.3）：`taskId` 与 `mode` 都由页面按真实数据传入，
 * 这里不做任何状态推测；没有进行中任务时横幅不渲染。
 */
import { PageShell } from "@/components/layout/PageShell";
import { cn } from "@/lib/utils/cn";

type Mode = "real" | "mock" | "offline" | "unknown";

const MODE_LABEL: Record<Mode, string> = {
  real: "真实模型",
  mock: "演示模式（mock 上游）",
  offline: "后端未连接",
  unknown: "状态检查中",
};

const MODE_STYLE: Record<Mode, string> = {
  real: "border-success/25 bg-success/[0.06] text-success",
  mock: "border-warn/30 bg-warn/[0.08] text-warn",
  offline: "border-danger/25 bg-danger/[0.06] text-danger",
  unknown: "border-line bg-black/[0.03] text-faint",
};

export function TopBar({ mode, taskLabel }: { mode: Mode; taskLabel?: string | null }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur-sm">
      <PageShell className="!py-3.5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-2.5">
            <span className="font-display text-[22px] font-semibold tracking-[0.18em] text-ink">
              履历
            </span>
            <span className="hidden text-[13px] text-faint sm:inline">
              履（鞋）＋ 历（经历）：一双鞋，就是履历上的一行
            </span>
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full border px-2.5 py-1 text-[12px] leading-none",
              MODE_STYLE[mode],
            )}
            title="上游运行模式"
          >
            {MODE_LABEL[mode]}
          </span>
        </div>

        {taskLabel ? (
          <div className="mt-3 flex items-center gap-2 rounded-[var(--radius-btn)] border border-line bg-surface px-3 py-2">
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-ink" />
            <p className="truncate text-[13px] text-muted">{taskLabel}</p>
            <button className="ml-auto shrink-0 text-[13px] text-ink underline underline-offset-4">
              回到进度
            </button>
          </div>
        ) : null}
      </PageShell>
    </header>
  );
}
