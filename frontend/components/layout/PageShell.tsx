import { cn } from "@/lib/utils/cn";

/** 页面外壳：统一最大宽度与留白节奏（8px 网格） */
export function PageShell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1200px] px-5 py-8 sm:px-8 sm:py-12", className)}>
      {children}
    </div>
  );
}
