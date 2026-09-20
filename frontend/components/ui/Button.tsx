import { cn } from "@/lib/utils/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white border-ink hover:bg-black",
  secondary: "bg-surface text-ink border-line hover:border-ink/40",
  ghost: "bg-transparent text-muted border-transparent hover:text-ink hover:bg-black/[0.03]",
  danger: "bg-surface text-danger border-line hover:border-danger/40",
};

const SIZES: Record<Size, string> = {
  // 触控目标 ≥ 44px（手机端硬要求）
  md: "h-11 px-5 text-[15px]",
  sm: "h-9 px-3.5 text-[13px]",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-btn)] border font-medium",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
    />
  );
}
