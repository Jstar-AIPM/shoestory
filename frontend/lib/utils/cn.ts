/** 极简 className 合并（避免为此引入 clsx/tailwind-merge 依赖） */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
