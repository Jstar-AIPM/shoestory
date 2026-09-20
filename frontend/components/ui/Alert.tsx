import { cn } from "@/lib/utils/cn";

export type AlertTone = "info" | "warn" | "danger";

const TONES: Record<AlertTone, string> = {
  info: "border-line bg-black/[0.02] text-muted",
  warn: "border-warn/30 bg-warn/[0.06] text-ink",
  danger: "border-danger/30 bg-danger/[0.05] text-ink",
};

/** 行内提示（纸白卡上）：错误不只用颜色表达，必须带文字说明 */
export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: AlertTone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={cn("rounded-[var(--radius-btn)] border px-4 py-3 text-[13.5px] leading-relaxed", TONES[tone], className)}
    >
      {title ? <p className="font-semibold">{title}</p> : null}
      {children}
    </div>
  );
}
