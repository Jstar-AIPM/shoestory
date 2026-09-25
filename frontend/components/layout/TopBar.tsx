/**
 * 顶栏：品牌 + 运行模式徽标 + 额度/身份
 *
 * 说明：`mode`、`quota` 都由页面按真实数据传入，这里不做任何状态推测。
 * 任务状态**不在顶栏显示**（2026-09-23 产品反馈）：状态条紧贴内容下方更好找，
 * 见 `components/ui/StatusBar.tsx`。
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
  quota,
  onLogout,
}: {
  mode: Mode;
  quota?: QuotaInfo | null;
  onLogout?: () => void;
}) {
  const modeTone = mode === "real" ? "success" : mode === "mock" ? "warn" : mode === "offline" ? "danger" : "neutral";

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur-sm">
      <PageShell className="!py-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* 品牌：顶栏只放英文小字标识，中文名「鞋历」留在首屏（2026-09-25 反馈 1：
              两个「鞋历」上下重复）。全大写 + 拉开字距是英文标识的常规做法，
              小字号下比中文粗体更"安静"，不会和首屏大标题抢视觉。 */}
          <div className="flex items-baseline gap-3">
            <span className="text-[13px] font-semibold uppercase tracking-[0.22em] text-white">
              Shoestory
            </span>
            <span className="hidden text-[12.5px] text-muted md:inline">收藏的不只是球鞋，是走过的日子</span>
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
      </PageShell>
    </header>
  );
}
