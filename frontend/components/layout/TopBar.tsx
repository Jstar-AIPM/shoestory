/**
 * 顶栏：品牌 + 运行模式徽标 + 额度/身份 + 「正在生成」横幅
 *
 * 说明：`taskId`、`mode`、`quota` 都由页面按真实数据传入，这里不做任何状态推测。
 */
import { PageShell } from "@/components/layout/PageShell";
import { StatusChip } from "@/components/ui/StatusChip";

type Mode = "real" | "mock" | "offline" | "unknown";

const MODE_LABEL: Record<Mode, string> = {
  real: "真实模型",
  mock: "演示模式（mock 上游）",
  offline: "后端未连接",
  unknown: "状态检查中",
};

export type QuotaInfo = {
  authRequired: boolean;
  role: "guest" | "admin" | null;
  remaining: number | null;
  canGenerate: boolean;
};

export function TopBar({
  mode,
  taskLabel,
  quota,
  onLogout,
}: {
  mode: Mode;
  taskLabel?: string | null;
  quota?: QuotaInfo | null;
  onLogout?: () => void;
}) {
  const modeTone = mode === "real" ? "success" : mode === "mock" ? "warn" : mode === "offline" ? "danger" : "neutral";

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur-sm">
      <PageShell className="!py-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <span className="text-[22px] font-extrabold tracking-wide text-white">履历</span>
            <span className="hidden text-[12.5px] text-muted sm:inline">履（鞋）＋ 历（经历）</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {quota?.authRequired ? (
              quota.role === "admin" ? (
                <StatusChip tone="progress">管理员 · 不限次</StatusChip>
              ) : (
                <StatusChip tone={quota.canGenerate ? "neutral" : "warn"}>
                  {quota.canGenerate ? `还可生成 ${quota.remaining ?? 0} 次` : "生成次数已用完"}
                </StatusChip>
              )
            ) : null}
            {quota?.role === "admin" ? (
              <a
                href="/admin"
                className="rounded-full border border-line bg-white/5 px-3 py-1 text-[12.5px] text-muted hover:text-ink"
              >
                管理员
              </a>
            ) : null}
            <StatusChip tone={modeTone as "success" | "warn" | "danger" | "neutral"}>{MODE_LABEL[mode]}</StatusChip>
            {quota?.authRequired && onLogout ? (
              <button
                onClick={onLogout}
                className="rounded-full border border-line bg-white/5 px-3 py-1 text-[12.5px] text-muted hover:text-ink"
              >
                退出
              </button>
            ) : null}
          </div>
        </div>

        {taskLabel ? (
          <div className="mt-3 flex items-center gap-2 rounded-[var(--radius-btn)] border border-line bg-surface px-3 py-2">
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[#57f287]" />
            <p className="truncate text-[13px] text-muted">{taskLabel}</p>
          </div>
        ) : null}
      </PageShell>
    </header>
  );
}
