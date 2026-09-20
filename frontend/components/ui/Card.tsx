import { cn } from "@/lib/utils/cn";

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <section
      className={cn(
        "rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-soft)]",
        className,
      )}
    >
      {children}
    </section>
  );
}

/** 骨架屏：只为「加载中」用，绝不冒充「空数据」 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-[var(--radius-btn)] bg-black/[0.05]", className)} />;
}
