import { cn } from "@/lib/utils/cn";

export type ChipTone = "success" | "progress" | "warn" | "danger" | "neutral";

/** 状态胶囊：用 Discord 的状态三色表达质检 / 进度 / 风险（只在墙面上使用） */
const TONES: Record<ChipTone, string> = {
  success: "border-success/30 bg-success/10 text-success",
  progress: "border-[#a5adff]/30 bg-[#5865f2]/15 text-[#a5adff]",
  warn: "border-warn/30 bg-warn/10 text-warn",
  danger: "border-danger/30 bg-danger/10 text-danger",
  neutral: "border-line bg-white/5 text-muted",
};

export function StatusChip({
  tone = "neutral",
  children,
  className,
}: {
  tone?: ChipTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("rounded-full border px-3 py-1 text-[12.5px] leading-none", TONES[tone], className)}>
      {children}
    </span>
  );
}
