import { cn } from "@/lib/utils/cn";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-11 w-full rounded-[var(--radius-btn)] border border-line bg-surface px-3.5",
        "text-[15px] text-ink placeholder:text-faint",
        "focus:border-ink/50 focus:outline-none",
        className,
      )}
    />
  );
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(
        "w-full rounded-[var(--radius-btn)] border border-line bg-surface px-3.5 py-2.5",
        "text-[15px] leading-relaxed text-ink placeholder:text-faint",
        "focus:border-ink/50 focus:outline-none",
        className,
      )}
    />
  );
}
